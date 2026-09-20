# Contractor Niagara environment packs

An environment pack lets a controls shop bring its exact Niagara target into a BACTalk run without asking BACTalk to execute untrusted Java. The uploaded ZIP, every declared asset, the normalized manifest, the compatibility result, generated program, and test evidence are bound into the run's approval hash.

## ZIP layout

`environment.json` must be at the archive root. Every other file must be declared by the manifest; undeclared files, symlinks, encrypted entries, unsafe paths, hash mismatches, oversized entries, and archive bombs are rejected.

```text
environment.json
modules/acmeControls-rt.jar
graphics/ahu-overview.px
```

## Manifest example

```json
{
  "schema_version": "1.0",
  "id": "acme-standard",
  "name": "Acme Niagara Standard",
  "version": "2026.09",
  "niagara_version": "4.14.0.162",
  "modules": [
    {
      "name": "acmeControls",
      "version": "3.2.1",
      "vendor": "Acme Controls",
      "preferred_symbol": "acme",
      "runtime_profiles": ["rt", "wb"],
      "artifact": "modules/acmeControls-rt.jar",
      "sha256": "<lowercase SHA-256 of the exact JAR>",
      "license_spdx": "LicenseRef-Acme-Proprietary",
      "redistribution": "shop_supplied_only",
      "required": true
    }
  ],
  "palettes": [
    {
      "id": "acme-hvac",
      "module": "acmeControls",
      "resource": "module://acmeControls/palette/acme-hvac.palette",
      "component_types": ["acmeControls:Reset"],
      "components": [
        {
          "type_spec": "acmeControls:Add",
          "behavior_kind": "add",
          "contract_version": "1.0",
          "inputs": {
            "a": {"niagara_slot": "inputLeft", "data_type": "numeric"},
            "b": {"niagara_slot": "inputRight", "data_type": "numeric"}
          },
          "outputs": {
            "out": {"niagara_slot": "sum", "data_type": "numeric"}
          },
          "properties": {"precision": 2},
          "config_properties": {}
        }
      ]
    }
  ],
  "graphics_templates": [
    {
      "id": "AhuOverview",
      "artifact": "graphics/ahu-overview.px",
      "sha256": "<lowercase SHA-256 of the exact PX file>",
      "media_type": "application/vnd.tridium.px"
    }
  ]
}
```

## PX template contract

A graphics requirement selects a template by exact id. PX templates remain the contractor's own Niagara XML and visual standard; BACTalk changes only explicit placeholders in element text or attribute values:

| Placeholder | Replacement |
| --- | --- |
| `{{BACTALK:VIEW_TITLE}}` | Declared view title |
| `{{BACTALK:EQUIPMENT_NAME}}` | Canonical equipment name |
| `{{BACTALK:POINT_ORD:ZoneTemp}}` | Exact generated point ORD |
| `{{BACTALK:POINT_LABEL:ZoneTemp}}` | Reviewed point label |
| `{{BACTALK:POINT_UNITS:ZoneTemp}}` | Declared units or an empty string |

Every point in the view contract must have at least one `POINT_ORD` placeholder. References to points outside the view, unknown placeholders, unresolved placeholders, DTD/entity declarations, script elements, and HTTP/HTTPS/JavaScript/data URIs fail closed. BACTalk parses and re-parses the generated XML but never renders or executes it. The package includes `niagara-graphics-plan.json` with source/output hashes and every exact binding.

For example, a contractor-owned value binding can keep all of its widget and conversion configuration while exposing only its ORD as a typed substitution:

```xml
<ValueBinding ord="{{BACTALK:POINT_ORD:ZoneTemp}}"/>
```

`component_types` inventories types a contractor template is allowed to contain. `components` is the smaller executable contract: each entry states which existing BACTalk IR behavior the proprietary block implements and maps every logical typed port to its exact Niagara slot. `properties` contains fixed Niagara property values. `config_properties` maps variable BACTalk block configuration into exact Niagara property names; compilation fails if a required parameter is absent, non-scalar, duplicated, or collides with a fixed property.

A graph may explicitly opt into one with:

```json
{"niagara_override": {"type_spec": "acmeControls:Add"}}
```

If the behavior, ports, data types, module, or type do not match, compilation stops. The JAR is inspected only as a ZIP inventory and is never class-loaded by BACTalk.

For an IR behavior with no stock Niagara lowering, BACTalk automatically uses the environment component only when exactly one component declares that behavior. Multiple candidates are an error until the graph names the exact `type_spec`. This is how a shop can provide an exact G36 `PIDWithReset` implementation: all three typed ports are declared and `k`, `Ti`, `Td`, `r`, `Ni`, `Nd`, limits, initial conditions, reset target, controller type, and action direction are mapped through `config_properties`. BACTalk will not silently replace it with `kitControl:LoopPoint`.

## Existing proxy-point binding

Add these optional columns to the contractor point CSV/XLSX:

| Column | Meaning |
| --- | --- |
| `niagara_ord` or `station_ord` | Exact existing point, for example `station:|slot:/Config/Drivers/BacnetNetwork/AHU_1/Points/SAT` |
| `niagara_write_priority` or `write_priority` | Niagara priority input `1`–`16` for a command/alarm output; defaults to `16` |

BACTalk never guesses a station path from a BACnet object ID. Exact ORDs generate `niagara-point-bindings.json`, a readback contract, and `BactalkPointBinder_<graph>.java`. The installer validates both endpoints and refuses to replace an existing different link.

## Station template mode

The shop profile controls what a supplied `.bog` means:

| `station_template_mode` | Behavior |
| --- | --- |
| `compare_only` | Analyze and diff the contractor reference without producing an assembled station. This is the default. |
| `insert` | Insert the generated program under the exact `station_folder`; the complete parent path must already exist and a same-name component is an error. |
| `replace` | Replace the exact same-name program under `station_folder`; the target must already exist and no outside component may reference one of its handles. |

Assembly happens only in the offline artifact. Generated handles and internal references are rebased above the station's existing handle space, unrelated components are preserved, and the approved `/export` returns `assembled-station.bog`. No running station is contacted.

## Qualification boundary

Static compatibility proves that the archives are safe to ingest and that declared type/slot contracts close. PX compilation additionally proves well-formed XML, complete declared-point substitution, and content hashes. It does not prove transitive module dependencies, module signatures, Niagara version compatibility, Workbench import, station restart, component runtime behavior, PX rendering/navigation, or field behavior. Those checks belong in a licensed disposable Niagara runtime and must be retained as target-profile evidence before the environment can become production-supported.
