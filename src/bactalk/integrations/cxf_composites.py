from __future__ import annotations

import copy
import hashlib
import json
import re
from collections import deque
from typing import Any

from bactalk.integrations.cxf_arrays import (
    ENGINE_ENUM_PACKAGES,
    ChildPort,
    ChildPortOracle,
    _element_expression,
    _grounded_booleans,
    _shape,
)
from bactalk.integrations.cxf_connections import normalize_connection_sets
from bactalk.integrations.cxf_importer import resolve_parameter_expression


class CxfCompositeAssemblyError(ValueError):
    pass


def _items(value: Any) -> list[dict[str, Any]]:
    if isinstance(value, list):
        return [item for item in value if isinstance(item, dict)]
    return [value] if isinstance(value, dict) else []


def _root(document: dict[str, Any]) -> dict[str, Any]:
    graph = document.get("@graph")
    if not isinstance(graph, list):
        raise CxfCompositeAssemblyError("CXF class document has no @graph array")
    roots = [
        node for node in graph if isinstance(node, dict) and _items(node.get("S231:containsBlock"))
    ]
    if len(roots) != 1:
        raise CxfCompositeAssemblyError(
            f"CXF class document requires exactly one composite root; found {len(roots)}"
        )
    return roots[0]


def _merge_connections(template: dict[str, Any], instance: dict[str, Any]) -> dict[str, Any]:
    merged = copy.deepcopy(template)
    for key, value in instance.items():
        if key != "S231:isConnectedTo" or key not in merged:
            merged[key] = copy.deepcopy(value)
            continue
        combined: list[dict[str, Any]] = []
        seen: set[str] = set()
        for reference in [*_items(merged[key]), *_items(value)]:
            token = json.dumps(reference, sort_keys=True, separators=(",", ":"))
            if token in seen:
                continue
            seen.add(token)
            combined.append(copy.deepcopy(reference))
        if not combined:
            merged.pop(key, None)
        else:
            merged[key] = combined[0] if len(combined) == 1 else combined
    return merged


def _literal_value(value: Any) -> float | bool | str | None:
    if isinstance(value, dict) and "@value" in value:
        raw = value["@value"]
        data_type = str(value.get("@type", ""))
        if data_type.endswith("boolean"):
            return str(raw).lower() == "true"
        if data_type.endswith(("double", "decimal", "float", "integer", "int")):
            try:
                return float(raw)
            except (TypeError, ValueError):
                return None
        return raw if isinstance(raw, str) else None
    if isinstance(value, (bool, int, float, str)):
        return value
    return None


def _parameter_scope(
    composite: dict[str, Any],
    nodes: dict[str, dict[str, Any]],
    parent_scope: dict[str, float | bool | str],
    modifications: frozenset[str] = frozenset(),
) -> dict[str, float | bool | str]:
    declarations: list[str] = []
    for key in ("S231:hasParameter", "S231:hasConstant"):
        declarations.extend(
            reference["@id"]
            for reference in _items(composite.get(key))
            if isinstance(reference.get("@id"), str)
        )
    values: dict[str, float | bool | str] = {}
    for identifier in declarations:
        node = nodes.get(identifier)
        if node is None:
            raise CxfCompositeAssemblyError(
                f"composite parameter declaration is missing: {identifier}"
            )
        value = _literal_value(node.get("S231:value"))
        if value is None:
            continue
        name = identifier.rsplit(".", 1)[-1]
        # Modelica component modifications commonly use ``p=p`` to bind the
        # child's parameter to the enclosing parameter. Resolve that against the
        # parent before the child declaration becomes an own-scope binding; OCE
        # correctly treats an unresolved own ``p=p`` as a declaration cycle.
        if value == name and name in parent_scope:
            value = parent_scope[name]
            node["S231:value"] = value
        elif identifier in modifications and isinstance(value, str):
            # A modification is an expression of the enclosing scope
            # (``final have_WSE=have_WSE and not have_airCoo``); the child's own
            # same-named parameter must not shadow the parent's while evaluating it.
            resolved = resolve_parameter_expression(value, parent_scope)
            if resolved != value and isinstance(resolved, (bool, int, float, str)):
                value = resolved
                node["S231:value"] = value
        values[name] = value

    for _ in range(max(1, len(values))):
        changed = False
        environment = {**parent_scope, **values}
        for name, value in list(values.items()):
            resolved = resolve_parameter_expression(value, environment)
            if resolved != value:
                values[name] = resolved
                changed = True
        if not changed:
            break

    for identifier in declarations:
        name = identifier.rsplit(".", 1)[-1]
        if name in values:
            nodes[identifier]["S231:value"] = values[name]
    return {**parent_scope, **values}


def _ground_member_values(
    nodes: dict[str, dict[str, Any]],
    scope: dict[str, float | bool | str],
) -> int:
    """Ground component modifications in their enclosing Modelica scope."""

    resolved_count = 0
    for _ in range(max(1, len(nodes))):
        changed = False
        for node in nodes.values():
            value = _literal_value(node.get("S231:value"))
            if not isinstance(value, str):
                continue
            resolved = resolve_parameter_expression(value, scope)
            if resolved == value or not isinstance(resolved, (bool, int, float, str)):
                continue
            node["S231:value"] = resolved
            resolved_count += 1
            changed = True
        if not changed:
            break
    return resolved_count


def _class_resolver(class_documents: dict[str, dict[str, Any]]) -> Any:
    def resolve_class_id(identifier: str) -> str | None:
        if identifier in class_documents:
            return identifier
        relative = identifier.removeprefix("ex:")
        candidates = [
            candidate
            for candidate in class_documents
            if candidate.removeprefix("ex:") == relative
            or candidate.removeprefix("ex:").endswith("." + relative)
        ]
        return candidates[0] if len(candidates) == 1 else None

    return resolve_class_id


def child_port_oracle(class_documents: dict[str, dict[str, Any]]) -> ChildPortOracle:
    """Port directions and grounded shapes of child composite instances.

    For a component whose class is one of ``class_documents``, return the ports the
    class declares, keyed by the instance-prefixed id, with each array port's shape
    resolved in the child's own scope: the instance's modifications (grounded in the
    parent scope) over the class defaults. This is the same scope the assembler gives
    the child when it instantiates it, so the parent's split of ``c.p`` into
    ``c.p__i`` and the child's split of its own boundary agree.
    """

    resolve_class_id = _class_resolver(class_documents)

    def oracle(
        component: dict[str, Any],
        by_id: dict[str, dict[str, Any]],
        parent_scope: dict[str, int | float | bool | str],
    ) -> dict[str, ChildPort] | None:
        declared = component.get("@type")
        instance_id = component.get("@id")
        if not isinstance(declared, str) or not isinstance(instance_id, str):
            return None
        class_id = resolve_class_id(declared)
        if class_id is None:
            return None
        template = class_documents[class_id]
        template_root = _root(template)
        template_nodes = {
            node["@id"]: node
            for node in template["@graph"]
            if isinstance(node, dict) and isinstance(node.get("@id"), str)
        }
        # A derived parent parameter (``have_pumChiWatPri=have_chiWat and (...)``) may
        # still be an expression; ground the parent scope before reading modifiers.
        parent_scope = _grounded_booleans(parent_scope)
        scope: dict[str, float | bool | str] = {}
        for key in ("S231:hasParameter", "S231:hasConstant"):
            for reference in _items(template_root.get(key)):
                identifier = reference.get("@id")
                if not isinstance(identifier, str):
                    continue
                name = identifier.rsplit(".", 1)[-1]
                modifier = by_id.get(f"{instance_id}.{name}")
                if modifier is not None and "S231:value" in modifier:
                    raw = modifier["S231:value"]
                    if component.get("S231:isArray") is True:
                        # every element of an instance array has the same class, so
                        # element 1's modification sizes the ports
                        raw = _element_expression(raw, (1,), {}, context=modifier["@id"])
                    value = _literal_value(raw)
                    if isinstance(value, str):
                        value = resolve_parameter_expression(value, dict(parent_scope))
                else:
                    value = _literal_value(template_nodes.get(identifier, {}).get("S231:value"))
                if isinstance(value, (bool, int, float, str)):
                    scope[name] = value
        for _ in range(max(1, len(scope))):
            changed = False
            for name, value in list(scope.items()):
                if not isinstance(value, str):
                    continue
                resolved = resolve_parameter_expression(value, scope)
                if resolved != value and isinstance(resolved, (bool, int, float, str)):
                    scope[name] = resolved
                    changed = True
            if not changed:
                break
        ports: dict[str, ChildPort] = {}
        for key, direction in (("S231:hasInput", "sink"), ("S231:hasOutput", "source")):
            for reference in _items(template_root.get(key)):
                identifier = reference.get("@id")
                if not isinstance(identifier, str) or not identifier.startswith(class_id + "."):
                    continue
                node = template_nodes.get(identifier, {})
                shape = (
                    _shape({**node, "@id": identifier}, scope)  # type: ignore[arg-type]
                    if node.get("S231:isArray") is True
                    else ()
                )
                port_type = node.get("@type")
                ports[instance_id + identifier[len(class_id) :]] = (
                    direction,
                    shape,
                    port_type if isinstance(port_type, str) else None,
                )
        return ports

    return oracle


_ICON_BASE = re.compile(r"^(?:[A-Za-z_][A-Za-z0-9_]*\.)*Icons\.[A-Za-z_][A-Za-z0-9_]*$")


def _drop_icon_only_extends(graph: list[Any]) -> list[dict[str, Any]]:
    """Remove ``extends`` clauses whose every base is an icon class.

    An icon base (``Modelica.Blocks.Icons.Block``) carries annotations only, no
    variables and no equations, so dropping it cannot change behaviour; the engine
    rejects any surviving ``extends``. Any other base stays and fails closed.
    """

    removed: list[dict[str, Any]] = []
    for node in graph:
        if not isinstance(node, dict) or "S231:extends" not in node:
            continue
        raw = node["S231:extends"]
        values = raw if isinstance(raw, list) else [raw]
        names = [
            value.get("@id", "") if isinstance(value, dict) else str(value) for value in values
        ]
        if names and all(
            _ICON_BASE.fullmatch(name.split("#")[-1].removeprefix("ex:")) for name in names
        ):
            node.pop("S231:extends")
            removed.append({"component": node.get("@id"), "extends": names})
    return removed


_ENUM_TYPE = re.compile(r"^(?:[A-Za-z_][A-Za-z0-9_]*\.)+Types\.[A-Za-z_][A-Za-z0-9_]*$")


def _strip_compile_time_enum_parameters(graph: list[Any]) -> list[dict[str, Any]]:
    """Drop enumeration parameters the engine cannot ground, once nothing reads them.

    A plant composite declares selectors such as ``chiIsoValTyp`` of type
    ``...Types.Actuator`` and binds them down its children. Their only runtime effect
    is on conditional components, which conditional pruning has already resolved;
    the engine cannot ground an enumeration literal, so a surviving declaration fails
    ingestion. A declaration is removed only when no other value or guard in its
    owner's scope still names it; otherwise it stays and the engine reports it.
    """

    nodes = {
        node["@id"]: node
        for node in graph
        if isinstance(node, dict) and isinstance(node.get("@id"), str)
    }
    owners: dict[str, dict[str, Any]] = {}
    for node in nodes.values():
        for reference in _items(node.get("S231:hasParameter")):
            if isinstance(reference.get("@id"), str):
                owners[reference["@id"]] = node
    candidates: dict[str, tuple[str, str]] = {}
    for identifier, owner in owners.items():
        node = nodes.get(identifier, {})
        raw_type = node.get("S231:isOfDataType")
        type_id = raw_type.get("@id") if isinstance(raw_type, dict) else raw_type
        type_name = str(type_id or "").rsplit("#", 1)[-1].removeprefix("ex:")
        value = node.get("S231:value")
        if (
            _ENUM_TYPE.fullmatch(type_name)
            and not type_name.startswith(ENGINE_ENUM_PACKAGES)
            and isinstance(value, str)
            and value.startswith(type_name + ".")
        ):
            candidates[identifier] = (str(owner.get("@id")), identifier.rsplit(".", 1)[-1])
    removed: list[dict[str, Any]] = []
    for identifier, (owner_id, label) in sorted(candidates.items()):
        pattern = re.compile(rf"\b{re.escape(label)}\b")
        used = any(
            other_id != identifier
            and other_id not in candidates
            and (other_id == owner_id or other_id.startswith(owner_id + "."))
            and any(
                isinstance(other.get(key), str) and pattern.search(other[key])
                for key in ("S231:value", "S231:conditionalExpression")
            )
            for other_id, other in nodes.items()
        )
        if used:
            continue
        owner = nodes[owner_id]
        kept = [
            reference
            for reference in _items(owner.get("S231:hasParameter"))
            if reference.get("@id") != identifier
        ]
        if kept:
            owner["S231:hasParameter"] = kept[0] if len(kept) == 1 else kept
        else:
            owner.pop("S231:hasParameter", None)
        removed.append({"parameter": identifier, "value": nodes[identifier].get("S231:value")})
    removed_ids = {item["parameter"] for item in removed}
    graph[:] = [
        node for node in graph if not (isinstance(node, dict) and node.get("@id") in removed_ids)
    ]
    return removed


def _inline_empty_composites(graph: list[Any], expanded_ids: set[str], root_id: str) -> list[str]:
    """Replace composites left with no blocks by the wires they carry.

    ``Utilities.PlaceholderLogical`` with ``have_inp = true`` loses its only block (the
    placeholder constant) to conditional pruning and keeps ``connect(u, y)``. A
    composite with no blocks is not a composite to the engine; it is a pass-through.
    Every driver of one of its ports is connected straight to what that port reaches,
    and the instance and its ports are removed.
    """

    nodes = {
        node["@id"]: node
        for node in graph
        if isinstance(node, dict) and isinstance(node.get("@id"), str)
    }
    empty = sorted(
        identifier
        for identifier in expanded_ids
        if identifier in nodes and not _items(nodes[identifier].get("S231:containsBlock"))
    )
    if not empty:
        return []
    prefixes = tuple(identifier + "." for identifier in empty)

    def inner(identifier: str) -> bool:
        return identifier in empty or identifier.startswith(prefixes)

    def targets(identifier: str) -> list[str]:
        return [
            item["@id"]
            for item in _items(nodes.get(identifier, {}).get("S231:isConnectedTo"))
            if isinstance(item.get("@id"), str)
        ]

    def resolve(identifier: str, seen: frozenset[str] = frozenset()) -> list[str]:
        if not inner(identifier):
            return [identifier]
        if identifier in seen:
            raise CxfCompositeAssemblyError(f"pass-through composite loops at {identifier}")
        reached: list[str] = []
        for target in targets(identifier):
            reached.extend(resolve(target, seen | {identifier}))
        return reached

    for node in graph:
        if not isinstance(node, dict) or inner(str(node.get("@id", ""))):
            continue
        source = str(node.get("@id", ""))
        current = targets(source)
        if not any(inner(target) for target in current):
            continue
        rewired: list[str] = []
        for target in current:
            for final in resolve(target):
                # an edge stored against the flow (``y1Hea`` -> ``ph.y``) resolves back
                # to its own port; the port's real driver already reaches it
                if final != source and final not in rewired:
                    rewired.append(final)
        if rewired:
            references = [{"@id": item} for item in rewired]
            node["S231:isConnectedTo"] = references[0] if len(references) == 1 else references
        else:
            node.pop("S231:isConnectedTo", None)
    for node in graph:
        if not isinstance(node, dict):
            continue
        for key in ("S231:containsBlock", "S231:hasInstance"):
            if key not in node:
                continue
            kept = [item for item in _items(node[key]) if not inner(str(item.get("@id", "")))]
            if kept:
                node[key] = kept[0] if len(kept) == 1 else kept
            else:
                node.pop(key, None)
    graph[:] = [
        node for node in graph if not (isinstance(node, dict) and inner(str(node.get("@id", ""))))
    ]
    if any(identifier == root_id for identifier in empty):
        raise CxfCompositeAssemblyError("the root composite has no blocks")
    return empty


def assemble_cxf_composites(
    root_document: dict[str, Any],
    class_documents: dict[str, dict[str, Any]],
    *,
    max_depth: int = 32,
    max_instances: int = 2_000,
    max_nodes: int = 100_000,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Instantiate separately emitted modelica-json class CXF into one hierarchy.

    modelica-json emits a root controller and its composite dependencies as
    separate JSON-LD documents. OCE's composite resolver requires the concrete
    instance hierarchy in one document. This assembler performs only exact
    prefix substitution, instance-parameter binding, and the existing bounded
    per-class normalization; it never invents a missing class or connection.
    """

    if not 1 <= max_depth <= 64:
        raise CxfCompositeAssemblyError("max_depth must be between 1 and 64")
    if not 1 <= max_instances <= 10_000:
        raise CxfCompositeAssemblyError("max_instances must be between 1 and 10000")
    if not 1 <= max_nodes <= 500_000:
        raise CxfCompositeAssemblyError("max_nodes must be between 1 and 500000")

    assembled = copy.deepcopy(root_document)
    root = _root(assembled)
    root_id = root.get("@id")
    if not isinstance(root_id, str):
        raise CxfCompositeAssemblyError("CXF root has no string @id")
    graph = assembled["@graph"]
    nodes = {
        node["@id"]: node
        for node in graph
        if isinstance(node, dict) and isinstance(node.get("@id"), str)
    }
    root_scope = _parameter_scope(root, nodes, {})
    queue: deque[tuple[str, int, dict[str, float | bool | str]]] = deque(
        (reference["@id"], 1, root_scope)
        for reference in _items(root.get("S231:containsBlock"))
        if isinstance(reference.get("@id"), str)
    )
    expanded_instances: list[dict[str, Any]] = []
    missing_classes: set[str] = set()
    removed_ids: set[str] = set()
    expanded_ids: set[str] = set()

    resolve_class_id = _class_resolver(class_documents)
    oracle = child_port_oracle(class_documents)

    while queue:
        instance_id, depth, parent_scope = queue.popleft()
        if instance_id in expanded_ids:
            continue
        if depth > max_depth:
            raise CxfCompositeAssemblyError(
                f"CXF composite depth exceeds {max_depth} at {instance_id}"
            )
        instance = nodes.get(instance_id)
        if instance is None:
            raise CxfCompositeAssemblyError(f"CXF composite instance is missing: {instance_id}")
        declared_class_id = instance.get("@type")
        class_id = (
            resolve_class_id(declared_class_id) if isinstance(declared_class_id, str) else None
        )
        if class_id is None:
            if isinstance(declared_class_id, str) and not declared_class_id.startswith(
                ("ex:Buildings.Controls.OBC.CDL.", "ex:CDL.", "S231:")
            ):
                missing_classes.add(declared_class_id)
            continue
        if len(expanded_ids) >= max_instances:
            raise CxfCompositeAssemblyError(f"CXF composite instance count exceeds {max_instances}")

        template = class_documents[class_id]
        template_root = _root(template)
        if template_root.get("@id") != class_id:
            raise CxfCompositeAssemblyError(
                f"CXF class identity mismatch: expected {class_id}, found "
                f"{template_root.get('@id')}"
            )

        # modelica-json writes a component-array element endpoint (``mul1[2].y``,
        # rewritten to ``mul1.y[2]``) as a full IRI with an encoded index; compact it
        # so it follows its instance like every other identifier.
        expanded = (
            template.get("@context", {}).get("ex")
            if isinstance(template.get("@context"), dict)
            else None
        )

        def compact(item: str, expanded: Any = expanded) -> str:
            if isinstance(expanded, str) and item.startswith(expanded):
                return "ex:" + item[len(expanded) :]
            return item

        def remap(
            value: Any,
            *,
            source_prefix: str = class_id,
            target_prefix: str = instance_id,
        ) -> Any:
            if isinstance(value, dict):
                remapped: dict[str, Any] = {}
                for key, item in value.items():
                    if key == "@id" and isinstance(item, str):
                        item = compact(item)
                        if item == source_prefix or item.startswith(source_prefix + "."):
                            item = target_prefix + item[len(source_prefix) :]
                        remapped[key] = item
                    else:
                        remapped[key] = remap(item)
                return remapped
            if isinstance(value, list):
                return [remap(item) for item in value]
            return value

        clones = [remap(copy.deepcopy(node)) for node in template["@graph"]]
        clone_nodes = {
            node["@id"]: node
            for node in clones
            if isinstance(node, dict) and isinstance(node.get("@id"), str)
        }
        modifications = frozenset(
            identifier
            for identifier in set(clone_nodes) & set(nodes)
            if "S231:value" in nodes[identifier]
        )
        for identifier in sorted(set(clone_nodes) & set(nodes)):
            clone_nodes[identifier] = _merge_connections(clone_nodes[identifier], nodes[identifier])
        instanced_graph = list(clone_nodes.values())
        instanced_root = clone_nodes.get(instance_id)
        if instanced_root is None:
            raise CxfCompositeAssemblyError(
                f"remapped CXF class has no instance root: {instance_id}"
            )
        # Relative Modelica references may be emitted as ``ex:Utilities.X``
        # while the class document root is fully qualified. Preserve the exact
        # resolved class identity once the match is unique.
        instanced_root["@type"] = class_id
        instance_scope = _parameter_scope(instanced_root, clone_nodes, parent_scope, modifications)
        grounded_member_value_count = _ground_member_values(
            clone_nodes,
            instance_scope,
        )
        normalized, normalization = normalize_connection_sets(
            {"@context": copy.deepcopy(assembled.get("@context", {})), "@graph": instanced_graph},
            child_ports=oracle,
        )
        normalized_nodes = {
            node["@id"]: node
            for node in normalized["@graph"]
            if isinstance(node, dict) and isinstance(node.get("@id"), str)
        }
        pruned = set(clone_nodes) - set(normalized_nodes)
        removed_ids.update(pruned)
        for identifier in pruned:
            nodes.pop(identifier, None)
        for identifier, node in normalized_nodes.items():
            if identifier in nodes:
                # A connector the parent created for this child (one element of a
                # split array port) carries the parent's edges; the child's own
                # version of it carries only the child's, so keep both.
                carried = (
                    []
                    if identifier in clone_nodes
                    else _items(nodes[identifier].get("S231:isConnectedTo"))
                )
                nodes[identifier].clear()
                nodes[identifier].update(
                    _merge_connections(node, {"S231:isConnectedTo": carried}) if carried else node
                )
            else:
                graph.append(node)
                nodes[identifier] = node
        expanded_ids.add(instance_id)
        expanded_instances.append(
            {
                "instance_id": instance_id,
                "class_id": class_id,
                "depth": depth,
                "node_count": len(normalized_nodes),
                "pruned_node_count": len(pruned),
                "grounded_member_value_count": grounded_member_value_count,
                "normalization": normalization,
            }
        )
        current_root = nodes.get(instance_id)
        if current_root is None:
            continue
        queue.extend(
            (reference["@id"], depth + 1, instance_scope)
            for reference in _items(current_root.get("S231:containsBlock"))
            if isinstance(reference.get("@id"), str)
        )
        if len(nodes) > max_nodes:
            raise CxfCompositeAssemblyError(f"CXF node count exceeds {max_nodes}")

    if removed_ids:
        graph[:] = [
            node
            for node in graph
            if not (
                isinstance(node, dict)
                and isinstance(node.get("@id"), str)
                and node["@id"] in removed_ids
            )
        ]
        for node in graph:
            if not isinstance(node, dict):
                continue
            references = _items(node.get("S231:isConnectedTo"))
            if not references:
                continue
            retained = [
                reference for reference in references if reference.get("@id") not in removed_ids
            ]
            if not retained:
                node.pop("S231:isConnectedTo", None)
            else:
                node["S231:isConnectedTo"] = retained[0] if len(retained) == 1 else retained

    inlined = _inline_empty_composites(assembled["@graph"], expanded_ids, root_id)
    icon_extends = _drop_icon_only_extends(assembled["@graph"])
    enum_parameters = _strip_compile_time_enum_parameters(assembled["@graph"])
    serialized = json.dumps(assembled, sort_keys=True, separators=(",", ":")).encode()
    return assembled, {
        "schema": "bactalk.cxf-composite-assembly/v1",
        "icon_only_extends_removed": icon_extends,
        "compile_time_enum_parameters_removed": enum_parameters,
        "pass_through_composites_inlined": inlined,
        "root_id": root_id,
        "available_class_count": len(class_documents),
        "expanded_instance_count": len(expanded_instances),
        "expanded_class_count": len({item["class_id"] for item in expanded_instances}),
        "maximum_depth": max((item["depth"] for item in expanded_instances), default=0),
        "node_count": len(assembled["@graph"]),
        "pruned_node_count": len(removed_ids),
        "missing_classes": sorted(missing_classes),
        "complete": not missing_classes,
        "assembled_sha256": hashlib.sha256(serialized).hexdigest(),
        "instances": expanded_instances,
    }


def flatten_cxf_topology(
    assembled: dict[str, Any],
    engine_report: dict[str, Any],
    *,
    root_id: str,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Project OCE's independently resolved topology back into flat CXF.

    OCE validates and resolves composite boundaries, but its CXF exporter
    intentionally defers enum-parameterized blocks. The topology surface still
    contains every validated elementary block, exact resolved edge, public
    boundary output, and catalog input name. This projection retains authored
    block/parameter metadata while replacing only composite boundaries and
    connection relations with those independently resolved facts.
    """

    graph = assembled.get("@graph")
    context = assembled.get("@context")
    blocks = engine_report.get("blocks")
    connections = engine_report.get("connections")
    boundary_outputs = engine_report.get("boundary_outputs")
    pass_through = engine_report.get("pass_through", [])
    if not isinstance(graph, list) or not isinstance(context, dict):
        raise CxfCompositeAssemblyError("assembled CXF has no graph/context")
    if not all(
        isinstance(value, list) for value in (blocks, connections, boundary_outputs, pass_through)
    ):
        raise CxfCompositeAssemblyError("OCE topology report is incomplete")

    prefixes = {
        key: value
        for key, value in context.items()
        if isinstance(key, str) and isinstance(value, str)
    }

    def expand(identifier: str) -> str:
        prefix, separator, remainder = identifier.partition(":")
        if separator and prefix in prefixes:
            return prefixes[prefix] + remainder
        return identifier

    authored_by_expanded = {
        expand(node["@id"]): node
        for node in graph
        if isinstance(node, dict) and isinstance(node.get("@id"), str)
    }
    authored_id = {expanded: node["@id"] for expanded, node in authored_by_expanded.items()}

    def compact(identifier: str) -> str:
        if identifier in authored_id:
            return authored_id[identifier]
        candidates = [
            (prefix, namespace)
            for prefix, namespace in prefixes.items()
            if identifier.startswith(namespace)
        ]
        if not candidates:
            return identifier
        prefix, namespace = max(candidates, key=lambda item: len(item[1]))
        return f"{prefix}:{identifier[len(namespace) :]}"

    expanded_root_id = expand(root_id)
    source_root = authored_by_expanded.get(expanded_root_id)
    if source_root is None:
        raise CxfCompositeAssemblyError(f"assembled CXF root is missing: {root_id}")

    block_paths: list[str] = []
    retained_expanded: set[str] = {expanded_root_id}
    root_refs = {
        reference["@id"]
        for key in (
            "S231:hasInput",
            "S231:hasOutput",
            "S231:hasParameter",
            "S231:hasConstant",
        )
        for reference in _items(source_root.get(key))
        if isinstance(reference.get("@id"), str)
    }
    retained_expanded.update(expand(identifier) for identifier in root_refs)

    resolved_inputs: dict[str, list[str]] = {}
    for record in blocks:
        if not isinstance(record, dict) or not isinstance(record.get("instance_path"), str):
            raise CxfCompositeAssemblyError("OCE topology contains an invalid block")
        path = record["instance_path"]
        component = authored_by_expanded.get(path)
        if component is None:
            raise CxfCompositeAssemblyError(
                f"OCE topology block is absent from authored CXF: {path}"
            )
        block_paths.append(path)
        retained_expanded.add(path)
        for key in (
            "S231:hasInput",
            "S231:hasOutput",
            "S231:hasParameter",
            "S231:hasConstant",
            "S231:hasInstance",
        ):
            retained_expanded.update(
                expand(reference["@id"])
                for reference in _items(component.get(key))
                if isinstance(reference.get("@id"), str)
            )

        topology_inputs = record.get("inputs")
        input_names = record.get("input_names")
        if not isinstance(topology_inputs, list) or not isinstance(input_names, list):
            raise CxfCompositeAssemblyError(f"OCE topology lacks catalog input names for {path}")
        if len(topology_inputs) != len(input_names) or any(
            not isinstance(name, str) for name in input_names
        ):
            raise CxfCompositeAssemblyError(
                f"OCE topology has non-scalar or unnamed inputs for {path}"
            )
        component_refs = [
            reference["@id"]
            for key in ("S231:hasInput", "S231:hasInstance")
            for reference in _items(component.get(key))
            if isinstance(reference.get("@id"), str)
        ]
        by_name = {identifier.rsplit(".", 1)[-1]: identifier for identifier in component_refs}
        try:
            resolved_inputs[path] = [by_name[name] for name in input_names]
        except KeyError as exc:
            raise CxfCompositeAssemblyError(
                f"authored connector {exc.args[0]} is missing for {path}"
            ) from exc

    retained_nodes: dict[str, dict[str, Any]] = {}
    synthesized_nodes: set[str] = set()
    for expanded in retained_expanded:
        node = authored_by_expanded.get(expanded)
        if node is None:
            # Current modelica-json permits connector/parameter instances to be
            # declared by hasInstance without emitting a separate graph node.
            # Preserve that exact resolved identity as a skeletal node so the
            # flattened edge relation has a subject; the primitive class catalog
            # remains authoritative for its port type and role.
            identifier = compact(expanded)
            retained_nodes[identifier] = {"@id": identifier}
            synthesized_nodes.add(identifier)
        else:
            retained_nodes[node["@id"]] = copy.deepcopy(node)
    for node in retained_nodes.values():
        node.pop("S231:isConnectedTo", None)

    root = retained_nodes[root_id]
    root["S231:containsBlock"] = [{"@id": compact(path)} for path in block_paths]
    edge_targets: dict[str, list[dict[str, str]]] = {}

    def add_edge(source: str, target: str) -> None:
        source_id = compact(source)
        target_id = compact(target)
        if source_id == target_id:
            # OCE reports a boundary output fed straight from a boundary input as its
            # own driver; the pass-through pair carries the real edge
            return
        for identifier in (source_id, target_id):
            if identifier not in retained_nodes:
                retained_nodes[identifier] = {"@id": identifier}
                synthesized_nodes.add(identifier)
        references = edge_targets.setdefault(source_id, [])
        if not any(reference["@id"] == target_id for reference in references):
            references.append({"@id": target_id})

    for record in blocks:
        path = record["instance_path"]
        for source, target in zip(record["inputs"], resolved_inputs[path], strict=True):
            if compact(source) != target:
                add_edge(source, target)
    for connection in connections:
        if not isinstance(connection, dict) or not all(
            isinstance(connection.get(key), str) for key in ("from", "to")
        ):
            raise CxfCompositeAssemblyError("OCE topology contains an invalid edge")
        add_edge(connection["from"], connection["to"])
    for output in boundary_outputs:
        if not isinstance(output, dict) or not all(
            isinstance(output.get(key), str) for key in ("driver_path", "path")
        ):
            raise CxfCompositeAssemblyError("OCE topology contains an invalid boundary output")
        add_edge(output["driver_path"], output["path"])
    for pair in pass_through:
        if not isinstance(pair, dict) or not all(
            isinstance(pair.get(key), str) for key in ("input", "output")
        ):
            raise CxfCompositeAssemblyError(
                "OCE topology contains an invalid boundary pass-through"
            )
        add_edge(pair["input"], pair["output"])
    for source, references in edge_targets.items():
        retained_nodes[source]["S231:isConnectedTo"] = (
            references[0] if len(references) == 1 else references
        )

    flattened_graph = [
        retained_nodes[node["@id"]]
        for node in graph
        if isinstance(node, dict) and node.get("@id") in retained_nodes
    ]
    flattened_graph.extend(
        retained_nodes[identifier]
        for identifier in sorted(synthesized_nodes)
        if identifier not in {node.get("@id") for node in flattened_graph if isinstance(node, dict)}
    )
    flattened = {"@context": copy.deepcopy(context), "@graph": flattened_graph}
    serialized = json.dumps(flattened, sort_keys=True, separators=(",", ":")).encode()
    return flattened, {
        "schema": "bactalk.cxf-topology-flattening/v1",
        "source_engine": engine_report.get("engine"),
        "source_model_id": engine_report.get("model_id"),
        "root_id": root_id,
        "block_count": len(block_paths),
        "connection_count": sum(len(items) for items in edge_targets.values()),
        "node_count": len(flattened_graph),
        "synthesized_instance_node_count": len(synthesized_nodes),
        "flattened_sha256": hashlib.sha256(serialized).hexdigest(),
    }
