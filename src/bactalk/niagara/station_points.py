"""Read a contractor station ``.bog`` as data: its BACnet devices and proxy points (N5).

Nothing here executes or modifies the station. The parser walks the object
graph, finds the BACnet driver structures Niagara writes (network → device →
``points`` extension → proxy points with a ``proxyExt``), and returns a plain
inventory with each point's ORD, handle, BACnet object, data type and units.
Handle checks stay with :mod:`bactalk.integrations.niagara_station`.

Structure per the Tridium BACnet driver guide (types are declared ``doc-only``
in the catalog supplement until Gate G-WB confirms them against a real station):

- ``bacnet:BacnetNetwork`` holds ``bacnet:BacnetDevice`` children;
- a device's ``points`` child is a ``bacnet:BacnetPointDeviceExt`` whose
  descendants are ``control:*Point``/``control:*Writable`` components carrying a
  ``proxyExt`` of type ``bacnet:Bacnet<Kind>ProxyExt`` with ``objectId``
  (``analogInput:1``) and ``propertyId`` (``presentValue``);
- the device's ``config``/``deviceObject`` gives its ``objectId``
  (``device:1001``) and its ``address`` gives the network address.
"""

from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass, field
from xml.etree import ElementTree

from bactalk.integrations.niagara_station import _read_bog

_MODULE_CACHE_KEY = "__bactalk_modules__"

_NUMERIC_PROXIES = {"BacnetNumericProxyExt"}
_BOOLEAN_PROXIES = {"BacnetBooleanProxyExt"}
_ENUM_PROXIES = {"BacnetEnumProxyExt"}
_STRING_PROXIES = {"BacnetStringProxyExt"}

_OBJECT_TYPE_DATA = {
    "analogInput": "numeric",
    "analogOutput": "numeric",
    "analogValue": "numeric",
    "binaryInput": "boolean",
    "binaryOutput": "boolean",
    "binaryValue": "boolean",
    "multiStateInput": "enum",
    "multiStateOutput": "enum",
    "multiStateValue": "enum",
}
_WRITABLE_OBJECT_TYPES = {
    "analogOutput",
    "analogValue",
    "binaryOutput",
    "binaryValue",
    "multiStateOutput",
    "multiStateValue",
}


@dataclass(frozen=True)
class StationPoint:
    ord: str
    """``station:|slot:/...`` ORD of the proxy point."""

    handle: str
    name: str
    device: str
    device_instance: int | None
    object_type: str | None
    object_instance: int | None
    property_id: str
    data_type: str | None
    units: str | None
    writable: bool
    type_spec: str
    path: tuple[str, ...]

    @property
    def bacnet_object(self) -> str | None:
        if self.object_type is None or self.object_instance is None:
            return None
        return f"{_kebab(self.object_type)},{self.object_instance}"


@dataclass(frozen=True)
class StationDevice:
    ord: str
    handle: str
    name: str
    device_instance: int | None
    address: str | None
    points: tuple[StationPoint, ...] = ()


@dataclass(frozen=True)
class StationInventory:
    networks: tuple[str, ...]
    devices: tuple[StationDevice, ...]
    warnings: tuple[str, ...] = field(default_factory=tuple)

    @property
    def points(self) -> tuple[StationPoint, ...]:
        return tuple(point for device in self.devices for point in device.points)

    def to_dict(self) -> dict[str, object]:
        return {
            "schema": "bactalk.station-inventory/v1",
            "networks": list(self.networks),
            "device_count": len(self.devices),
            "point_count": len(self.points),
            "warnings": list(self.warnings),
            "devices": [
                {
                    "name": device.name,
                    "ord": device.ord,
                    "device_instance": device.device_instance,
                    "address": device.address,
                    "points": [
                        {
                            "name": point.name,
                            "ord": point.ord,
                            "device": point.device,
                            "device_instance": point.device_instance,
                            "bacnet_object": point.bacnet_object,
                            "property_id": point.property_id,
                            "data_type": point.data_type,
                            "units": point.units,
                            "writable": point.writable,
                            "type": point.type_spec,
                        }
                        for point in device.points
                    ],
                }
                for device in self.devices
            ],
        }


def _kebab(camel: str) -> str:
    out = []
    for char in camel:
        if char.isupper():
            out.append("-" + char.lower())
        else:
            out.append(char)
    return "".join(out)


def _modules_in_order(root: ElementTree.Element) -> dict[int, dict[str, str]]:
    """Symbol table in effect at each element (document order, as Niagara writes)."""

    modules: dict[str, str] = {}
    table: dict[int, dict[str, str]] = {}
    for element in root.iter("p"):
        for token in (element.get("m") or "").split():
            symbol, _, module = token.partition("=")
            if symbol and module:
                modules[symbol] = module
        table[id(element)] = dict(modules)
    return table


def _resolved(element: ElementTree.Element, table: dict[int, dict[str, str]]) -> str | None:
    raw = element.get("t")
    if raw is None:
        return None
    symbol, _, name = raw.partition(":")
    module = table.get(id(element), {}).get(symbol, symbol)
    return f"{module}:{name}"


def _children(element: ElementTree.Element) -> Iterator[ElementTree.Element]:
    return (child for child in element if child.tag == "p")


def _child(element: ElementTree.Element, name: str) -> ElementTree.Element | None:
    return next((child for child in _children(element) if child.get("n") == name), None)


def _first_value(element: ElementTree.Element, name: str) -> str | None:
    for item in element.iter("p"):
        if item.get("n") == name and item.get("v") is not None:
            return item.get("v")
    return None


def _units_from_facets(facets: str | None) -> str | None:
    if not facets:
        return None
    for part in facets.split("|"):
        key, _, rest = part.partition("=")
        if key == "units" and rest.startswith("u:"):
            name = rest[2:].split(";", 1)[0]
            return None if name in {"", "null"} else name
    return None


def parse_station_inventory(content: bytes) -> StationInventory:
    """Parse a station ``.bog``; returns every BACnet device and proxy point as data."""

    root, _ = _read_bog(content, "station")
    table = _modules_in_order(root)
    station_root = next(_children(root))
    networks: list[str] = []
    devices: list[StationDevice] = []
    warnings: list[str] = []

    def walk(element: ElementTree.Element, path: tuple[str, ...]) -> None:
        for child in _children(element):
            name = child.get("n")
            if name is None:
                continue
            child_path = (*path, name)
            type_spec = _resolved(child, table) or ""
            if type_spec.endswith(":BacnetNetwork"):
                networks.append(_ord(child_path))
                for device in _children(child):
                    device_type = _resolved(device, table) or ""
                    device_name = device.get("n")
                    if device_name is None or not device_type.endswith(":BacnetDevice"):
                        continue
                    devices.append(_device(device, (*child_path, device_name), table, warnings))
                continue
            walk(child, child_path)

    walk(station_root, ())
    return StationInventory(
        networks=tuple(networks), devices=tuple(devices), warnings=tuple(warnings)
    )


def _ord(path: tuple[str, ...]) -> str:
    return "station:|slot:/" + "/".join(path)


def _device(
    element: ElementTree.Element,
    path: tuple[str, ...],
    table: dict[int, dict[str, str]],
    warnings: list[str],
) -> StationDevice:
    name = path[-1]
    handle = (element.get("h") or "").lower()
    instance: int | None = None
    config = _child(element, "config")
    if config is not None:
        raw = _first_value(config, "objectId")
        if raw and raw.startswith("device:"):
            try:
                instance = int(raw.split(":", 1)[1])
            except ValueError:
                warnings.append(f"{name}: unparseable device objectId {raw!r}")
    address = _first_value(element, "address")
    points: list[StationPoint] = []
    points_ext = _child(element, "points")
    if points_ext is not None:
        for point_path, point in _proxy_points(points_ext, (*path, "points"), table):
            points.append(_point(point, point_path, name, instance, table, warnings))
    if not handle:
        warnings.append(f"device {name} has no handle")
    return StationDevice(
        ord=_ord(path),
        handle=handle,
        name=name,
        device_instance=instance,
        address=address,
        points=tuple(points),
    )


def _proxy_points(
    element: ElementTree.Element,
    path: tuple[str, ...],
    table: dict[int, dict[str, str]],
) -> Iterator[tuple[tuple[str, str | None], ElementTree.Element]]:
    """Yield ``((path, ...), element)`` for every component with a BACnet proxyExt."""

    for child in _children(element):
        name = child.get("n")
        if name is None:
            continue
        child_path = (*path, name)
        proxy = _child(child, "proxyExt")
        if proxy is not None and "Bacnet" in (_resolved(proxy, table) or ""):
            yield child_path, child  # type: ignore[misc]
            continue
        yield from _proxy_points(child, child_path, table)


def _point(
    element: ElementTree.Element,
    path: tuple[str, ...],
    device: str,
    device_instance: int | None,
    table: dict[int, dict[str, str]],
    warnings: list[str],
) -> StationPoint:
    proxy = _child(element, "proxyExt")
    assert proxy is not None
    proxy_type = _resolved(proxy, table) or ""
    proxy_name = proxy_type.split(":", 1)[-1]
    object_type: str | None = None
    object_instance: int | None = None
    raw = _first_value(proxy, "objectId")
    if raw and ":" in raw:
        kind, _, number = raw.partition(":")
        object_type = kind
        try:
            object_instance = int(number)
        except ValueError:
            warnings.append(f"{'/'.join(path)}: unparseable objectId {raw!r}")
    property_id = _first_value(proxy, "propertyId") or "presentValue"
    if proxy_name in _NUMERIC_PROXIES:
        data_type: str | None = "numeric"
    elif proxy_name in _BOOLEAN_PROXIES:
        data_type = "boolean"
    elif proxy_name in _ENUM_PROXIES:
        data_type = "enum"
    elif proxy_name in _STRING_PROXIES:
        data_type = "string"
    else:
        data_type = _OBJECT_TYPE_DATA.get(object_type or "")
    facets = _child(element, "facets")
    type_spec = _resolved(element, table) or ""
    writable = type_spec.endswith("Writable") or (object_type in _WRITABLE_OBJECT_TYPES)
    handle = (element.get("h") or "").lower()
    if not handle:
        warnings.append(f"{'/'.join(path)}: proxy point has no handle")
    return StationPoint(
        ord=_ord(path),
        handle=handle,
        name=path[-1],
        device=device,
        device_instance=device_instance,
        object_type=object_type,
        object_instance=object_instance,
        property_id=property_id,
        data_type=data_type,
        units=_units_from_facets(facets.get("v") if facets is not None else None),
        writable=writable,
        type_spec=type_spec,
        path=path,
    )
