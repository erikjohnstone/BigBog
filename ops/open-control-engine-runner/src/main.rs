use std::env;
use std::fs;
use std::process::ExitCode;

use oce_api::{Engine, PointValueType, Value};
use serde_json::json;

fn inspect(path: &str) -> Result<serde_json::Value, String> {
    let bytes = fs::read(path).map_err(|error| format!("cannot read CXF: {error}"))?;
    let mut engine = Engine::in_memory();
    let report = engine.load_cxf(&bytes).map_err(|error| {
        let diagnostics = error
            .all_diagnostics()
            .take(100)
            .map(|diagnostic| {
                format!(
                    "{}|{}|{}|{}",
                    diagnostic.severity.as_str(),
                    diagnostic.code.as_str(),
                    diagnostic.subject.as_deref().unwrap_or("<none>"),
                    diagnostic.message.chars().take(500).collect::<String>()
                )
            })
            .collect::<Vec<_>>()
            .join("\n");
        if diagnostics.is_empty() {
            format!("CXF validation failed: {error}")
        } else {
            format!("CXF validation failed: {error}\n{diagnostics}")
        }
    })?;
    let topology = engine.topology();
    let points = engine
        .io()
        .iter()
        .map(|point| {
            json!({
                "path": point.path,
                "direction": format!("{:?}", point.direction),
                "value_type": format!("{:?}", point.value_type),
                "io_class": format!("{:?}", point.io_class),
                "unit": point.unit,
                "display_unit": point.display_unit,
                "quantity": point.quantity,
                "min": point.min,
                "max": point.max,
            })
        })
        .collect::<Vec<_>>();
    let blocks = topology
        .blocks
        .iter()
        .map(|block| {
            json!({
                "instance_path": block.instance_path,
                "class_iri": block.class_iri,
                "inputs": block.inputs,
                "outputs": block.outputs,
            })
        })
        .collect::<Vec<_>>();
    let connections = topology
        .connections
        .iter()
        .map(|connection| json!({"from": connection.from, "to": connection.to}))
        .collect::<Vec<_>>();
    Ok(json!({
        "engine": "open-control-engine",
        "model_id": report.model_id.0.as_ref(),
        "block_count": report.block_count,
        "stateful_blocks": report.stateful_blocks,
        "warning_count": report.warnings.len(),
        "point_count": points.len(),
        "points": points,
        "blocks": blocks,
        "connections": connections,
        "external_inputs": topology.external_inputs,
        "boundary_outputs": topology.boundary_outputs.iter().map(|output| {
            json!({"path": output.path, "driver_path": output.driver_path})
        }).collect::<Vec<_>>(),
    }))
}

fn value_from_json(
    value: &serde_json::Value,
    expected: PointValueType,
    point: &str,
) -> Result<Value, String> {
    match expected {
        PointValueType::Real => value
            .as_f64()
            .map(Value::Real)
            .ok_or_else(|| format!("input {point} requires a real value")),
        PointValueType::Int => value
            .as_i64()
            .map(Value::Integer)
            .ok_or_else(|| format!("input {point} requires an integer value")),
        PointValueType::Bool => value
            .as_bool()
            .map(Value::Boolean)
            .ok_or_else(|| format!("input {point} requires a boolean value")),
    }
}

fn value_json(value: Value) -> serde_json::Value {
    match value {
        Value::Real(item) => json!({"type": "real", "value": item}),
        Value::Integer(item) => json!({"type": "integer", "value": item}),
        Value::Boolean(item) => json!({"type": "boolean", "value": item}),
        Value::String(item) => json!({"type": "string", "value": item.as_ref()}),
        Value::Enum { class, ordinal } => json!({
            "type": "enum",
            "class": format!("{class:?}"),
            "value": ordinal,
        }),
    }
}

fn simulate(path: &str, scenario_path: &str) -> Result<serde_json::Value, String> {
    let bytes = fs::read(path).map_err(|error| format!("cannot read CXF: {error}"))?;
    let scenario_bytes =
        fs::read(scenario_path).map_err(|error| format!("cannot read scenario: {error}"))?;
    let scenario: serde_json::Value = serde_json::from_slice(&scenario_bytes)
        .map_err(|error| format!("scenario is invalid JSON: {error}"))?;
    let samples = scenario
        .get("samples")
        .and_then(serde_json::Value::as_array)
        .ok_or_else(|| "scenario.samples must be an array".to_string())?;
    if samples.is_empty() || samples.len() > 100_000 {
        return Err("scenario.samples must contain 1-100000 entries".to_string());
    }
    let collect = scenario
        .get("collect")
        .and_then(serde_json::Value::as_array)
        .ok_or_else(|| "scenario.collect must be an array".to_string())?
        .iter()
        .map(|item| {
            item.as_str()
                .map(str::to_string)
                .ok_or_else(|| "scenario.collect entries must be strings".to_string())
        })
        .collect::<Result<Vec<_>, _>>()?;
    if collect.is_empty() || collect.len() > 10_000 {
        return Err("scenario.collect must contain 1-10000 points".to_string());
    }

    let mut engine = Engine::in_memory();
    engine
        .load_cxf(&bytes)
        .map_err(|error| format!("CXF validation failed: {error}"))?;
    let input_types = engine
        .io()
        .iter()
        .map(|point| (point.path.clone(), point.value_type))
        .collect::<std::collections::HashMap<_, _>>();
    let mut trace = Vec::with_capacity(samples.len());
    let mut previous_time: Option<f64> = None;
    for (index, sample) in samples.iter().enumerate() {
        let time = sample
            .get("time")
            .and_then(serde_json::Value::as_f64)
            .ok_or_else(|| format!("samples[{index}].time must be finite numeric"))?;
        if !time.is_finite() || previous_time.is_some_and(|previous| time < previous) {
            return Err(format!(
                "samples[{index}].time must be finite and monotonic"
            ));
        }
        let inputs = sample
            .get("inputs")
            .and_then(serde_json::Value::as_object)
            .ok_or_else(|| format!("samples[{index}].inputs must be an object"))?;
        for (point, raw) in inputs {
            let expected = input_types
                .get(point)
                .copied()
                .ok_or_else(|| format!("unknown scenario input: {point}"))?;
            engine
                .set_input(point, value_from_json(raw, expected, point)?)
                .map_err(|error| format!("cannot stage input {point}: {error}"))?;
        }
        engine
            .tick(time)
            .map_err(|error| format!("tick {index} failed: {error}"))?;
        let outputs = collect
            .iter()
            .map(|point| {
                engine
                    .get_output(point)
                    .map(|value| (point.clone(), value_json(value)))
                    .map_err(|error| format!("cannot read output {point}: {error}"))
            })
            .collect::<Result<serde_json::Map<_, _>, _>>()?;
        trace.push(json!({"time": time, "outputs": outputs}));
        previous_time = Some(time);
    }
    Ok(json!({
        "schema": "bactalk.oce-trace/v1",
        "engine": "open-control-engine",
        "sample_count": trace.len(),
        "collect": collect,
        "trace": trace,
    }))
}

fn main() -> ExitCode {
    let mut args = env::args().skip(1);
    let Some(command) = args.next() else {
        eprintln!("usage: bactalk-oce-runner inspect <cxf.jsonld>");
        return ExitCode::from(2);
    };
    let Some(path) = args.next() else {
        eprintln!("missing CXF path");
        return ExitCode::from(2);
    };
    let result = match command.as_str() {
        "inspect" if args.next().is_none() => inspect(&path),
        "simulate" => match args.next() {
            Some(scenario) if args.next().is_none() => simulate(&path, &scenario),
            _ => Err("usage: bactalk-oce-runner simulate <cxf.jsonld> <scenario.json>".into()),
        },
        _ => Err("usage: bactalk-oce-runner inspect <cxf.jsonld>".into()),
    };
    match result {
        Ok(result) => {
            println!("{}", result);
            ExitCode::SUCCESS
        }
        Err(error) => {
            eprintln!("{error}");
            ExitCode::FAILURE
        }
    }
}
