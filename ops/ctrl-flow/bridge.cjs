#!/usr/bin/env node

"use strict";

const fs = require("fs");
const path = require("path");

const root = path.resolve(__dirname, "../..");
const clientRoot = path.join(root, ".vendor/ctrl-flow-dev/client");
const register = path.join(
  clientRoot,
  "node_modules/ts-node/register/transpile-only",
);

if (!fs.existsSync(register + ".js") && !fs.existsSync(register)) {
  throw new Error(
    "ctrl-flow client dependencies are missing; run scripts/install_ctrl_flow.sh",
  );
}

process.env.TS_NODE_COMPILER_OPTIONS = JSON.stringify({
  module: "commonjs",
  moduleResolution: "node",
  resolveJsonModule: true,
  esModuleInterop: true,
  jsx: "react-jsx",
  target: "ES2020",
});
require(register);

const dataPath = path.join(clientRoot, "src/data/templates.json");
const templateData = JSON.parse(fs.readFileSync(dataPath, "utf8"));
const {
  ConfigContext,
  constructSelectionPath,
} = require(path.join(clientRoot, "src/interpreter/interpreter.ts"));
const { mapToDisplayOptions } = require(
  path.join(clientRoot, "src/interpreter/display-option.ts"),
);

const templates = new Map(
  templateData.templates.map((template) => [template.modelicaPath, template]),
);
const options = Object.fromEntries(
  templateData.options.map((option) => [option.modelicaPath, option]),
);

function fail(message) {
  process.stderr.write(`${message}\n`);
  process.exit(2);
}

function readPayload() {
  const input = fs.readFileSync(0, "utf8").trim();
  if (!input) return {};
  const parsed = JSON.parse(input);
  if (!parsed || Array.isArray(parsed) || typeof parsed !== "object") {
    fail("ctrl-flow bridge payload must be an object");
  }
  return parsed;
}

function optionClosure(rootPath) {
  const seen = new Set();
  const pending = [rootPath];
  while (pending.length) {
    const optionPath = pending.pop();
    if (!optionPath || seen.has(optionPath)) continue;
    seen.add(optionPath);
    const option = options[optionPath];
    if (option && Array.isArray(option.options)) {
      pending.push(...option.options);
    }
  }
  return [...seen].filter((optionPath) => options[optionPath]);
}

function flattenDisplay(items, groups = [], output = []) {
  for (const item of items) {
    if (Object.prototype.hasOwnProperty.call(item, "items")) {
      flattenDisplay(item.items, [...groups, item.groupName], output);
      continue;
    }
    const choices = Array.isArray(item.choices)
      ? item.choices
          .filter(Boolean)
          .map((choice) => ({
            value: choice.modelicaPath,
            label: choice.name || choice.modelicaPath.split(".").pop(),
          }))
      : undefined;
    output.push({
      // ConfigContext resolves selections against the declared option path.
      // The upstream display mapper also exposes a composition-parent path,
      // which is useful for layout but is not the lookup key used by getValue.
      selection_path: constructSelectionPath(item.modelicaPath, item.scope),
      composition_parent_path: item.parentModelicaPath,
      modelica_path: item.modelicaPath,
      instance_path: item.scope,
      name: item.name,
      groups,
      selection_type: item.selectionType,
      value: item.value,
      ...(choices ? { choices } : {}),
      ...(item.booleanChoices ? { boolean_choices: [true, false] } : {}),
    });
  }
  return output;
}

function makeContext(template, selections) {
  const config = {
    id: "bactalk-ctrl-flow-configuration",
    name: "BACTalk configuration",
    isLocked: false,
    quantity: 1,
    systemPath: template.systemTypes[0],
    templatePath: template.modelicaPath,
    selections,
    evaluatedValues: {},
  };
  return new ConfigContext(template, config, options, selections);
}

function normalizeValue(field, value) {
  if (field.selection_type === "Boolean") {
    if (value === true || value === false) return value;
    if (value === "true") return true;
    if (value === "false") return false;
    fail(`${field.selection_path} requires a Boolean value`);
  }
  const choices = field.choices || [];
  if (choices.length && !choices.some((choice) => choice.value === value)) {
    fail(`${field.selection_path} contains a value outside the upstream choice set`);
  }
  if (!["string", "number", "boolean"].includes(typeof value) && value !== null) {
    fail(`${field.selection_path} contains an unsupported value type`);
  }
  return value;
}

function renderConfiguration(template, requestedSelections) {
  const selections = {};
  const rejected = [];
  const pending = new Map(Object.entries(requestedSelections));

  // Validate in dependency order. A choice can reveal another choice (for
  // example selecting no draw-through fan reveals the blow-through fan). The
  // request object's order is not trusted: each pass accepts the first choice
  // that is valid in the configuration built so far, then evaluates again.
  for (let pass = 0; pass <= Object.keys(requestedSelections).length; pass += 1) {
    const context = makeContext(template, selections);
    const allowed = new Map(
      flattenDisplay(mapToDisplayOptions(context)).map((field) => [
        field.selection_path,
        field,
      ]),
    );
    let accepted = false;
    for (const [selectionPath, value] of pending.entries()) {
      const field = allowed.get(selectionPath);
      if (!field || !context.isValidSelection(selectionPath)) continue;
      selections[selectionPath] = normalizeValue(field, value);
      pending.delete(selectionPath);
      accepted = true;
      break;
    }
    if (!accepted) break;
  }
  for (const selectionPath of pending.keys()) {
    rejected.push({
      selection_path: selectionPath,
      reason: "not displayed for the configured upstream option tree",
    });
  }

  const drawPath =
    "Buildings.Templates.AirHandlersFans.VAVMultiZone.fanSupDra-fanSupDra";
  const blowPath =
    "Buildings.Templates.AirHandlersFans.VAVMultiZone.fanSupBlo-fanSupBlo";
  const noFan = "Buildings.Templates.Components.Fans.None";
  function isValidFanPlacementPair(selectionPath) {
    if (![drawPath, blowPath].includes(selectionPath)) return false;
    if (!(drawPath in selections) || !(blowPath in selections)) return false;
    return (
      (selections[drawPath] === noFan && selections[blowPath] !== noFan) ||
      (selections[blowPath] === noFan && selections[drawPath] !== noFan)
    );
  }

  // Remove stale selections after dependencies settle. ctrl-flow's VAV AHU
  // has one intentional reciprocal enable pair: choosing a fan placement
  // hides both placement selectors in the final display tree. Retain only that
  // explicitly valid one-fan/one-none pair; all other hidden values fail closed.
  for (let pass = 0; pass <= Object.keys(selections).length; pass += 1) {
    const context = makeContext(template, selections);
    const visiblePaths = new Set(
      flattenDisplay(mapToDisplayOptions(context)).map(
        (field) => field.selection_path,
      ),
    );
    const stale = Object.keys(selections).filter(
      (selectionPath) =>
        (!visiblePaths.has(selectionPath) || !context.isValidSelection(selectionPath)) &&
        !isValidFanPlacementPair(selectionPath),
    );
    if (!stale.length) break;
    for (const selectionPath of stale) {
      delete selections[selectionPath];
      if (!rejected.some((item) => item.selection_path === selectionPath)) {
        rejected.push({
          selection_path: selectionPath,
          reason: "became hidden after upstream dependency evaluation",
        });
      }
    }
  }

  const context = makeContext(template, selections);
  const displayTree = mapToDisplayOptions(context);
  const fields = flattenDisplay(displayTree);
  return {
    display_tree: displayTree,
    fields,
    selections,
    rejected_selections: rejected,
    evaluated_values: context.getEvaluatedValues(),
  };
}

const action = process.argv[2];
const payload = readPayload();
let result;

if (action === "catalog") {
  result = {
    templates: templateData.templates.map((template) => {
      const closure = optionClosure(template.modelicaPath).map(
        (optionPath) => options[optionPath],
      );
      return {
        id: template.modelicaPath,
        name: template.name,
        system_types: template.systemTypes,
        path_modifiers: template.pathModifiers,
        schedule_option_paths: template.scheduleOptionPaths,
        option_count: closure.length,
        visible_option_count: closure.filter((option) => option.visible).length,
        conditional_option_count: closure.filter(
          (option) => option.enable && typeof option.enable === "object",
        ).length,
        replaceable_option_count: closure.filter((option) => option.replaceable)
          .length,
      };
    }),
    system_types: templateData.systemTypes,
    option_count: templateData.options.length,
    schedule_option_count: templateData.scheduleOptions.length,
    project: templateData.project,
  };
} else if (action === "schema" || action === "configure") {
  const templateId = payload.template_id;
  const template = templates.get(templateId);
  if (!template) fail(`unknown ctrl-flow template: ${templateId}`);
  const selections = payload.selections || {};
  if (!selections || Array.isArray(selections) || typeof selections !== "object") {
    fail("selections must be an object");
  }
  if (Object.keys(selections).length > 500) {
    fail("at most 500 ctrl-flow selections are accepted");
  }
  result = {
    template,
    ...renderConfiguration(template, selections),
  };
} else {
  fail(`unknown ctrl-flow bridge action: ${action || "<missing>"}`);
}

process.stdout.write(JSON.stringify(result));
