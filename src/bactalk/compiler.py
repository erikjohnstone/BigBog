from __future__ import annotations

import zipfile
from dataclasses import dataclass
from pathlib import Path
from xml.etree import ElementTree

from bactalk.domain import (
    Block,
    BlockKind,
    ControlGraph,
    DataType,
    DeliverableRequirements,
    ScheduleRequirement,
)
from bactalk.integrations.environment_pack import (
    CustomComponentContract,
    EnvironmentPackManifest,
)
from bactalk.integrations.niagara_bindings import program_root_ord_for
from bactalk.niagara_extensions import apply_point_units, inject_fixed_interval_histories


@dataclass(frozen=True)
class _CustomLowering:
    contract: CustomComponentContract
    emitted_type_spec: str
    module_name: str
    module_symbol: str


class NiagaraCompiler:
    """Translate validated BACTalk IR into a Niagara `.bog` using pybog."""

    SLOT_NAMES: dict[BlockKind, dict[str, str]] = {
        BlockKind.NUMERIC_INPUT: {"out": "out"},
        BlockKind.BOOLEAN_INPUT: {"out": "out"},
        BlockKind.NUMERIC_OUTPUT: {"in": "in16", "out": "out"},
        BlockKind.BOOLEAN_OUTPUT: {"in": "in16", "out": "out"},
        BlockKind.NUMERIC_CONST: {"out": "out"},
        BlockKind.BOOLEAN_CONST: {"out": "out"},
        BlockKind.ADD: {"a": "inA", "b": "inB", "out": "out"},
        BlockKind.SUBTRACT: {"a": "inA", "b": "inB", "out": "out"},
        BlockKind.MULTIPLY: {"a": "inA", "b": "inB", "out": "out"},
        BlockKind.DIVIDE: {"a": "inA", "b": "inB", "out": "out"},
        BlockKind.MINIMUM: {"a": "inA", "b": "inB", "out": "out"},
        BlockKind.MAXIMUM: {"a": "inA", "b": "inB", "out": "out"},
        BlockKind.AVERAGE: {"a": "inA", "b": "inB", "out": "out"},
        BlockKind.GREATER_THAN: {"a": "inA", "b": "inB", "out": "out"},
        BlockKind.GREATER_THAN_OR_EQUAL: {"a": "inA", "b": "inB", "out": "out"},
        BlockKind.LESS_THAN: {"a": "inA", "b": "inB", "out": "out"},
        BlockKind.LESS_THAN_OR_EQUAL: {"a": "inA", "b": "inB", "out": "out"},
        BlockKind.EQUAL: {"a": "inA", "b": "inB", "out": "out"},
        BlockKind.NOT_EQUAL: {"a": "inA", "b": "inB", "out": "out"},
        BlockKind.AND: {"a": "inA", "b": "inB", "out": "out"},
        BlockKind.OR: {"a": "inA", "b": "inB", "out": "out"},
        BlockKind.XOR: {"a": "inA", "b": "inB", "out": "out"},
        BlockKind.NOT: {"in": "in", "out": "out"},
        BlockKind.NUMERIC_SWITCH: {
            "selector": "inSwitch",
            "when_true": "inTrue",
            "when_false": "inFalse",
            "out": "out",
        },
        BlockKind.BOOLEAN_SWITCH: {
            "selector": "inSwitch",
            "when_true": "inTrue",
            "when_false": "inFalse",
            "out": "out",
        },
        BlockKind.BOOLEAN_DELAY: {"in": "in", "out": "out"},
        BlockKind.ONE_SHOT: {"in": "in", "out": "out"},
        BlockKind.NUMERIC_LATCH: {"in": "in", "clock": "clock", "out": "out"},
        BlockKind.BOOLEAN_LATCH: {"in": "in", "clock": "clock", "out": "out"},
        BlockKind.RESET: {
            "in": "inA",
            "input_low": "inputLowLimit",
            "input_high": "inputHighLimit",
            "output_low": "outputLowLimit",
            "output_high": "outputHighLimit",
            "out": "out",
        },
        BlockKind.PI_LOOP: {
            "enable": "loopEnable",
            "controlled_variable": "controlledVariable",
            "setpoint": "setpoint",
            "direct": "loopAction",
            "out": "out",
        },
    }

    def compile(
        self,
        graph: ControlGraph,
        destination: Path,
        *,
        deliverables: DeliverableRequirements | None = None,
        environment: EnvironmentPackManifest | None = None,
        units: dict[str, str | None] | None = None,
    ) -> Path:
        """Compile ``graph`` to ``destination``.

        ``units`` maps a point block id to the unit string the job declares for
        that point. pybog cannot set units, so the numeric point facets are
        rewritten after the archive is saved; a point without a resolvable unit
        keeps Niagara's null unit.
        """
        custom_registry = self._custom_registry(environment)
        custom_contracts = list(
            {item.contract.type_spec: item for item in custom_registry.values()}.values()
        )
        custom_by_block: dict[str, _CustomLowering] = {}
        unsupported: set[str] = set()
        for block in graph.blocks:
            override = block.config.get("niagara_override")
            lowering = None
            if override is not None:
                requested_type = str(override["type_spec"])
                lowering = custom_registry.get(requested_type)
                if lowering is None:
                    raise ValueError(
                        f"block {block.id} requests custom Niagara type {requested_type!r}, "
                        "but the contractor environment has no typed component contract"
                    )
                if lowering.contract.behavior_kind != block.kind:
                    raise ValueError(
                        f"custom Niagara type {requested_type!r} models "
                        f"{lowering.contract.behavior_kind.value}, not {block.kind.value}"
                    )
            elif block.kind not in self.SLOT_NAMES:
                candidates = [
                    item
                    for item in custom_contracts
                    if item.contract.behavior_kind == block.kind
                ]
                if len(candidates) == 1:
                    lowering = candidates[0]
                elif len(candidates) > 1:
                    choices = ", ".join(
                        sorted(item.contract.type_spec for item in candidates)
                    )
                    raise ValueError(
                        f"block {block.id} has multiple custom Niagara lowerings for "
                        f"{block.kind.value}: {choices}; set config.niagara_override.type_spec"
                    )
                else:
                    unsupported.add(block.kind.value)
            if lowering is not None:
                custom_by_block[block.id] = lowering
        unsupported = sorted(unsupported)
        if unsupported:
            raise ValueError(
                "Niagara compiler cannot lower these BACTalk IR block kinds: "
                + ", ".join(unsupported)
            )
        try:
            from bog_builder import BogFolderBuilder
        except ImportError as exc:  # pragma: no cover - installation guard
            raise RuntimeError("pybog is required to compile Niagara artifacts") from exc

        destination.parent.mkdir(parents=True, exist_ok=True)
        builder = BogFolderBuilder(graph.name, debug=False)
        for block in graph.blocks:
            lowering = custom_by_block.get(block.id)
            self._add_block(builder, block, custom=lowering)
        by_id = {block.id: block for block in graph.blocks}
        for schedule in deliverables.schedules if deliverables else []:
            self._add_schedule(builder, by_id, schedule)
        for link in graph.links:
            source = by_id[link.source]
            target = by_id[link.target]
            source_lowering = custom_by_block.get(link.source)
            target_lowering = custom_by_block.get(link.target)
            source_slot = (
                source_lowering.contract.outputs[link.source_slot].niagara_slot
                if source_lowering is not None
                else self.SLOT_NAMES[source.kind][link.source_slot]
            )
            target_slot = (
                target_lowering.contract.inputs[link.target_slot].niagara_slot
                if target_lowering is not None
                else self.SLOT_NAMES[target.kind][link.target_slot]
            )
            if source_lowering is not None or target_lowering is not None:
                self._add_typed_direct_link(
                    builder,
                    link.source,
                    source_slot,
                    link.target,
                    target_slot,
                )
            else:
                builder.add_link(
                    link.source,
                    source_slot,
                    link.target,
                    target_slot,
                )
        builder.save(str(destination))
        apply_point_units(destination, graph, units or {})
        if custom_by_block:
            module_aliases = {
                item.module_symbol: item.module_name for item in custom_by_block.values()
            }
            self._rewrite_module_aliases(destination, module_aliases)
        if deliverables:
            inject_fixed_interval_histories(
                destination,
                graph,
                deliverables.histories,
                program_root_ord=program_root_ord_for(
                    graph.name,
                    deliverables.shop_profile,
                ),
                units=units,
            )
        return destination

    @staticmethod
    def _add_schedule(
        builder: object,
        blocks: dict[str, Block],
        schedule: ScheduleRequirement,
    ) -> None:
        if schedule.id in blocks:
            raise ValueError(f"schedule id conflicts with graph block id: {schedule.id}")
        target = blocks.get(schedule.output_point)
        if target is None:
            raise ValueError(
                f"schedule {schedule.id} output point is absent from the compiled graph: "
                f"{schedule.output_point}"
            )
        if target.kind not in {BlockKind.BOOLEAN_INPUT, BlockKind.NUMERIC_INPUT}:
            raise ValueError(
                f"schedule {schedule.id} must drive an input block, not {target.kind.value}"
            )
        if schedule.holiday_calendar is not None:
            raise ValueError(
                f"schedule {schedule.id} declares holiday calendar "
                f"{schedule.holiday_calendar!r}, but special-event lowering is not qualified"
            )

        days = (
            "sunday",
            "monday",
            "tuesday",
            "wednesday",
            "thursday",
            "friday",
            "saturday",
        )
        week: dict[str, dict] = {day: {"day": {}} for day in days}
        for period in sorted(
            schedule.weekly_periods,
            key=lambda item: (days.index(item.day), item.start, item.end),
        ):
            day = week[period.day]["day"]
            day.setdefault("times", []).append(
                {
                    "start": f"{period.start}:00.000",
                    "finish": f"{period.end}:00.000",
                    "effectiveValue": {"value": period.value},
                }
            )
        properties = {
            "defaultOutput": {"value": schedule.default_value},
            "effective": {
                "start": {
                    "yearSchedule": {"alwaysEffective": True},
                    "monthSchedule": {"singleSelection": True},
                    "daySchedule": {"singleSelection": True},
                    "weekdaySchedule": {"singleSelection": True},
                },
                "end": {
                    "yearSchedule": {"alwaysEffective": True},
                    "monthSchedule": {"singleSelection": True},
                    "daySchedule": {"singleSelection": True},
                    "weekdaySchedule": {"singleSelection": True},
                },
            },
            "schedule": {"specialEvents": {}, "week": week},
            "out": {"value": schedule.default_value},
        }
        if target.kind == BlockKind.BOOLEAN_INPUT:
            builder.add_boolean_schedule(schedule.id, properties=properties)
            schedule_type = DataType.BOOLEAN
        else:
            builder.add_numeric_schedule(schedule.id, properties=properties)
            schedule_type = DataType.NUMERIC
        expected = DataType.BOOLEAN if target.kind == BlockKind.BOOLEAN_INPUT else DataType.NUMERIC
        if schedule_type != expected:  # defensive guard for future schedule types
            raise ValueError(f"schedule {schedule.id} data type does not match its output point")
        builder.add_link(schedule.id, "out", schedule.output_point, "in16")

    @staticmethod
    def _custom_registry(
        environment: EnvironmentPackManifest | None,
    ) -> dict[str, _CustomLowering]:
        if environment is None:
            return {}
        modules = {item.name: item for item in environment.modules}
        registry: dict[str, _CustomLowering] = {}
        for palette in environment.palettes:
            module = modules[palette.module]
            symbol = module.preferred_symbol or module.name
            for contract in palette.components:
                _, type_name = contract.type_spec.split(":", 1)
                lowering = _CustomLowering(
                    contract=contract,
                    emitted_type_spec=f"{symbol}:{type_name}",
                    module_name=module.name,
                    module_symbol=symbol,
                )
                for key in {
                    contract.type_spec,
                    f"{module.name}:{type_name}",
                    lowering.emitted_type_spec,
                }:
                    existing = registry.get(key)
                    if existing is not None and existing != lowering:
                        raise ValueError(f"ambiguous custom Niagara type contract: {key}")
                    registry[key] = lowering
        return registry

    @staticmethod
    def _add_typed_direct_link(
        builder: object,
        source_name: str,
        source_slot: str,
        target_name: str,
        target_slot: str,
    ) -> None:
        links = getattr(builder, "_links", None)
        if not isinstance(links, list):
            raise RuntimeError(
                "installed pybog no longer exposes the verified link adapter boundary"
            )
        links.append(
            {
                "source_name": source_name,
                "source_slot": source_slot,
                "target_name": target_name,
                "target_slot": target_slot,
                "link_type": "b:Link",
                "converter_type": None,
            }
        )

    @staticmethod
    def _rewrite_module_aliases(destination: Path, aliases: dict[str, str]) -> None:
        with zipfile.ZipFile(destination) as archive:
            entries = {name: archive.read(name) for name in archive.namelist()}
        try:
            root = ElementTree.fromstring(entries["file.xml"])
        except (KeyError, ElementTree.ParseError) as exc:
            raise RuntimeError(
                "pybog emitted an invalid archive while lowering custom types"
            ) from exc
        matched: set[str] = set()
        for element in root.iter():
            type_spec = element.attrib.get("t", "")
            if ":" not in type_spec:
                continue
            symbol = type_spec.split(":", 1)[0]
            module_name = aliases.get(symbol)
            if module_name is not None:
                element.set("m", f"{symbol}={module_name}")
                matched.add(symbol)
        if matched != set(aliases):
            raise RuntimeError("custom Niagara module alias was not emitted into the .bog")
        ElementTree.indent(root, space="  ")
        entries["file.xml"] = ElementTree.tostring(
            root,
            encoding="utf-8",
            xml_declaration=True,
        )
        temporary = destination.with_suffix(".custom.tmp")
        with zipfile.ZipFile(temporary, "w", compression=zipfile.ZIP_DEFLATED) as archive:
            for name in sorted(entries):
                info = zipfile.ZipInfo(name, date_time=(1980, 1, 1, 0, 0, 0))
                info.compress_type = zipfile.ZIP_DEFLATED
                info.external_attr = 0o644 << 16
                archive.writestr(info, entries[name])
        temporary.replace(destination)

    @staticmethod
    def _add_block(
        builder: object,
        block: Block,
        *,
        custom: _CustomLowering | None = None,
    ) -> None:
        if custom is not None:
            add_component = getattr(builder, "_add_component", None)
            if not callable(add_component):
                raise RuntimeError(
                    "installed pybog no longer exposes the verified custom-component boundary"
                )
            properties: dict[str, float | bool | str] = dict(custom.contract.properties)
            for config_name, property_name in custom.contract.config_properties.items():
                if config_name not in block.config:
                    raise ValueError(
                        f"custom Niagara type {custom.contract.type_spec!r} requires "
                        f"block config.{config_name}"
                    )
                value = block.config[config_name]
                if isinstance(value, bool):
                    properties[property_name] = str(value).lower()
                elif isinstance(value, (int, float, str)):
                    properties[property_name] = value
                else:
                    raise ValueError(
                        f"block {block.id} config.{config_name} cannot be emitted as a "
                        "Niagara component property"
                    )
            add_component(
                custom.emitted_type_spec,
                block.id,
                properties=properties,
            )
            return
        kind = block.kind
        if kind in {BlockKind.NUMERIC_INPUT, BlockKind.NUMERIC_OUTPUT}:
            builder.add_numeric_writable(
                block.id,
                default_value=float(block.config.get("default", 0.0)),
            )
        elif kind in {BlockKind.BOOLEAN_INPUT, BlockKind.BOOLEAN_OUTPUT}:
            builder.add_boolean_writable(
                block.id,
                default_value=bool(block.config.get("default", False)),
            )
        elif kind == BlockKind.NUMERIC_CONST:
            builder.add_numeric_const(block.id, value=float(block.config["value"]))
        elif kind == BlockKind.BOOLEAN_CONST:
            builder.add_boolean_const(block.id, value=bool(block.config["value"]))
        elif kind == BlockKind.BOOLEAN_DELAY:
            builder.add_boolean_delay(
                block.id,
                on_delay=round(float(block.config.get("on_delay_seconds", 0.0)) * 1000),
                off_delay=round(float(block.config.get("off_delay_seconds", 0.0)) * 1000),
            )
        elif kind == BlockKind.ONE_SHOT:
            builder.add_one_shot(block.id)
        elif kind == BlockKind.NUMERIC_LATCH:
            builder.add_numeric_latch(block.id)
        elif kind == BlockKind.BOOLEAN_LATCH:
            builder.add_boolean_latch(block.id)
        elif kind == BlockKind.RESET:
            builder.add_reset(block.id)
        elif kind == BlockKind.PI_LOOP:
            limits = (
                float(block.config.get("output_min", 0.0)),
                float(block.config.get("output_max", 100.0)),
                float(block.config.get("bias", 0.0)),
                float(block.config.get("disabled_output", 0.0)),
            )
            if limits != (0.0, 100.0, 0.0, 0.0):
                raise ValueError(
                    "Niagara LoopPoint lowering currently requires output_min=0, "
                    "output_max=100, bias=0, and disabled_output=0"
                )
            builder.add_loop_point(
                block.id,
                properties={
                    "loopEnable": {"value": False},
                    "controlledVariable": {"value": 0.0},
                    "setpoint": {"value": 0.0},
                    "proportionalConstant": {
                        "value": float(block.config.get("proportional_constant", 1.0))
                    },
                    "integralConstant": {
                        "value": float(block.config.get("integral_constant", 0.0))
                    },
                },
            )
        else:
            method_name = {
                BlockKind.ADD: "add_add",
                BlockKind.SUBTRACT: "add_subtract",
                BlockKind.MULTIPLY: "add_multiply",
                BlockKind.DIVIDE: "add_divide",
                BlockKind.MINIMUM: "add_minimum",
                BlockKind.MAXIMUM: "add_maximum",
                BlockKind.AVERAGE: "add_average",
                BlockKind.GREATER_THAN: "add_greater_than",
                BlockKind.GREATER_THAN_OR_EQUAL: "add_greater_than_equal",
                BlockKind.LESS_THAN: "add_less_than",
                BlockKind.LESS_THAN_OR_EQUAL: "add_less_than_equal",
                BlockKind.EQUAL: "add_equal",
                BlockKind.NOT_EQUAL: "add_not_equal",
                BlockKind.AND: "add_and",
                BlockKind.OR: "add_or",
                BlockKind.XOR: "add_xor",
                BlockKind.NOT: "add_not",
                BlockKind.NUMERIC_SWITCH: "add_numeric_switch",
                BlockKind.BOOLEAN_SWITCH: "add_boolean_switch",
            }.get(kind)
            if method_name is None:
                raise ValueError(f"Niagara compiler does not support {kind}")
            getattr(builder, method_name)(block.id)
