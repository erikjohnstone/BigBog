"""Generate the contractor station fixture for N5: one AHU and 25 VAVs with messy names.

Writes ``tests/fixtures/native-bog/station-ahu-25vav.bog``: a Niagara station
skeleton with a BACnet network, 26 devices and their proxy points named the way
field technicians name them (mixed abbreviations, separators and casing). The
structure follows the Tridium BACnet driver guide; it is a fixture for the
parser, the mapper and station assembly, not a claim about any real station.

Usage::

    PYTHONPATH=src .venv/bin/python scripts/make_station_fixture.py
"""

from __future__ import annotations

import io
import zipfile
from pathlib import Path
from xml.etree import ElementTree

ROOT = Path(__file__).resolve().parents[1]
DESTINATION = ROOT / "tests" / "fixtures" / "native-bog" / "station-ahu-25vav.bog"

# (name, object type, instance, units facet or None)
AHU_POINTS = [
    ("AHU1_SA-T", "analogInput", 1, "fahrenheit"),
    ("AHU1 RA_T", "analogInput", 2, "fahrenheit"),
    ("AHU-1 OAT", "analogInput", 3, "fahrenheit"),
    ("AHU1_MAT", "analogInput", 4, "fahrenheit"),
    ("AHU1 DSP", "analogInput", 5, "inches of water"),
    ("AHU1_SF_STS", "binaryInput", 1, None),
    ("AHU1_RF_STS", "binaryInput", 2, None),
    ("AHU1 SF SPD CMD", "analogOutput", 1, "percent"),
    ("AHU1_RF_SPD", "analogOutput", 2, "percent"),
    ("AHU1_OAD_CMD", "analogOutput", 3, "percent"),
    ("AHU1 RAD CMD", "analogOutput", 4, "percent"),
    ("AHU1_CLG_VLV", "analogOutput", 5, "percent"),
    ("AHU1_HTG_VLV", "analogOutput", 6, "percent"),
    ("AHU1_SF_CMD", "binaryOutput", 1, None),
    ("AHU1_RF_CMD", "binaryOutput", 2, None),
    ("AHU1 SAT STPT", "analogValue", 1, "fahrenheit"),
    ("AHU1_DSP_SP", "analogValue", 2, "inches of water"),
    ("AHU1_OCC", "binaryValue", 1, None),
    ("AHU1 FRZ STAT", "binaryInput", 3, None),
    ("AHU1_CO2", "analogInput", 6, "ppm"),
]

VAV_TEMPLATES = [
    ("{tag} ZN-T", "analogInput", 1, "fahrenheit"),
    ("{tag}_DAT", "analogInput", 2, "fahrenheit"),
    ("{tag} AFL CFM", "analogInput", 3, "cfm"),
    ("{tag}_DMPR POS", "analogOutput", 1, "percent"),
    ("{tag}_RHT VLV", "analogOutput", 2, "percent"),
    ("{tag} CLG STPT", "analogValue", 1, "fahrenheit"),
    ("{tag}_HTG_SP", "analogValue", 2, "fahrenheit"),
    ("{tag} OCC", "binaryValue", 1, None),
    ("{tag}_WIN_STS", "binaryInput", 1, None),
    ("{tag} CO2", "analogInput", 4, "ppm"),
]

_UNITS = {
    "fahrenheit": "units=u:fahrenheit;°F;(K);*0.5555555555555556+255.37222222222223;",
    "percent": "units=u:percent;%;;;",
    "inches of water": "units=u:inches of water;in/wc;(m-1)(kg)(s-2);*248.84;",
    "cfm": "units=u:cubic feet per minute;cfm;(m3)(s-1);*0.0004719474432;",
    "ppm": "units=u:parts per million;ppm;;;",
}


class _Handles:
    def __init__(self) -> None:
        self.value = 0

    def next(self) -> str:
        self.value += 1
        return format(self.value, "x")


def _slot_name(name: str) -> str:
    cleaned = "".join(ch if ch.isalnum() or ch == "_" else "_" for ch in name)
    return cleaned if cleaned[0].isalpha() or cleaned[0] == "_" else f"P_{cleaned}"


def _device(
    parent: ElementTree.Element,
    handles: _Handles,
    name: str,
    instance: int,
    address: str,
    points: list[tuple[str, str, int, str | None]],
) -> None:
    device = ElementTree.SubElement(
        parent, "p", {"n": _slot_name(name), "h": handles.next(), "t": "bacnet:BacnetDevice"}
    )
    ElementTree.SubElement(device, "p", {"n": "address", "t": "bacnet:BacnetAddress", "v": address})
    config = ElementTree.SubElement(
        device, "p", {"n": "config", "h": handles.next(), "t": "bacnet:BacnetDeviceConfig"}
    )
    ElementTree.SubElement(
        config,
        "p",
        {"n": "objectId", "t": "bacnet:BacnetObjectIdentifier", "v": f"device:{instance}"},
    )
    extension = ElementTree.SubElement(
        device, "p", {"n": "points", "h": handles.next(), "t": "bacnet:BacnetPointDeviceExt"}
    )
    for point_name, object_type, object_instance, units in points:
        numeric = object_type.startswith("analog")
        writable = object_type.endswith(("Output", "Value"))
        if numeric:
            type_spec = "c:NumericWritable" if writable else "c:NumericPoint"
            proxy_type = "bacnet:BacnetNumericProxyExt"
        else:
            type_spec = "c:BooleanWritable" if writable else "c:BooleanPoint"
            proxy_type = "bacnet:BacnetBooleanProxyExt"
        point = ElementTree.SubElement(
            extension, "p", {"n": _slot_name(point_name), "h": handles.next(), "t": type_spec}
        )
        proxy = ElementTree.SubElement(point, "p", {"n": "proxyExt", "t": proxy_type})
        ElementTree.SubElement(
            proxy,
            "p",
            {
                "n": "objectId",
                "t": "bacnet:BacnetObjectIdentifier",
                "v": f"{object_type}:{object_instance}",
            },
        )
        ElementTree.SubElement(
            proxy,
            "p",
            {"n": "propertyId", "t": "bacnet:BacnetPropertyIdentifier", "v": "presentValue"},
        )
        if numeric:
            facets = _UNITS.get(units or "", "units=u:null;;;;")
            ElementTree.SubElement(
                point,
                "p",
                {"n": "facets", "t": "b:Facets", "v": f"{facets}|precision=i:1"},
            )
        if writable:
            ElementTree.SubElement(point, "p", {"n": "in16", "f": "tsL"})


def build() -> bytes:
    handles = _Handles()
    root = ElementTree.Element(
        "bajaObjectGraph",
        {"version": "4.0", "reversibleEncodingKeySource": "none", "FIPSEnabled": "false"},
    )
    station = ElementTree.SubElement(
        root,
        "p",
        {"m": "b=baja c=control d=driver bacnet=bacnet", "t": "b:Station", "h": handles.next()},
    )
    services = ElementTree.SubElement(
        station, "p", {"n": "Services", "h": handles.next(), "t": "b:ServiceContainer"}
    )
    ElementTree.SubElement(services, "p", {"n": "Notes", "t": "b:WsTextBlock", "v": "fixture"})
    drivers = ElementTree.SubElement(
        station, "p", {"n": "Drivers", "h": handles.next(), "t": "d:DriverContainer"}
    )
    network = ElementTree.SubElement(
        drivers, "p", {"n": "BacnetNetwork", "h": handles.next(), "t": "bacnet:BacnetNetwork"}
    )
    _device(network, handles, "AHU_1", 1001, "ip:192.168.10.11", AHU_POINTS)
    for index in range(1, 26):
        floor = 1 + (index - 1) // 10
        tag = f"VAV-{floor}-{index:02d}"
        points = [
            (template.format(tag=tag), object_type, instance, units)
            for template, object_type, instance, units in VAV_TEMPLATES
        ]
        _device(
            network, handles, f"VAV_{floor}_{index:02d}", 2000 + index, f"mstp:1:{index}", points
        )
    ElementTree.SubElement(station, "p", {"n": "Apps", "h": handles.next(), "t": "b:Folder"})
    ElementTree.indent(root, space=" ")
    xml = b'<?xml version="1.0" encoding="UTF-8"?>\n' + ElementTree.tostring(root, encoding="utf-8")
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        info = zipfile.ZipInfo("file.xml", date_time=(1980, 1, 1, 0, 0, 0))
        info.compress_type = zipfile.ZIP_DEFLATED
        archive.writestr(info, xml)
    return buffer.getvalue()


def main() -> None:
    DESTINATION.parent.mkdir(parents=True, exist_ok=True)
    DESTINATION.write_bytes(build())
    print(f"wrote {DESTINATION} ({DESTINATION.stat().st_size} bytes)")


if __name__ == "__main__":
    main()
