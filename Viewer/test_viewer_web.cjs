"use strict";

const assert = require("node:assert/strict");
const {readFileSync} = require("node:fs");
const {join} = require("node:path");
const {test} = require("node:test");
const vm = require("node:vm");
const source = readFileSync(join(__dirname, "web/app.js"), "utf8");

function notebookContext() {
  const context = vm.createContext({
    state: {drafts: new Map(), saving: new Set(), saveFailures: new Set(), saveTimers: new Map(), notebookCompatible: false},
    structuredClone, clearTimeout,
    messages: [],
    notify(message) { context.messages.push(message); },
    updateSaveState() {},
    async changeAnnotations() { throw new Error("Unexpected save request"); },
  });
  vm.runInContext(source.slice(source.indexOf("function blankNotebookFields()"), source.indexOf("function exportRecord(")), context);
  vm.runInContext(source.slice(source.indexOf("async function saveNotebook("), source.indexOf("function queueDraft(")), context);
  return context;
}

test("legacy notes become input notes without obsolete field names", () => {
  const context = notebookContext();
  const fields = context.normalizeNotebookFields({background: "Black", objects: "Red", object_relationships: "Touching", transformations: "Move", strategy: "Align"});
  assert.equal(Object.keys(fields).length, 8);
  assert.equal(fields.input_background, "Black");
  assert.equal(fields.input_objects, "Red");
  assert.equal(fields.input_object_relationships, "Touching");
  assert.equal(fields.output_background, "");
  assert.equal(fields.output_objects, "");
  assert.equal(fields.output_object_relationships, "");
  assert.equal(fields.transformations, "Move");
  assert.equal(fields.strategy, "Align");
  assert.equal("background" in fields, false);
  assert.equal(context.normalizeNotebookFields({...fields, background: "Old", input_background: "Edited"}).input_background, "Edited");
});

test("an older server keeps drafts and explains the required restart", async () => {
  const context = notebookContext();
  const draft = {fields: context.normalizeNotebookFields({background: "Keep this note"})};
  context.state.drafts.set("a", draft);
  await context.saveNotebook("a");
  await context.saveNotebook("a");
  assert.equal(context.state.drafts.get("a"), draft);
  assert.equal(context.state.saveFailures.has("a"), true);
  assert.equal(context.messages.length, 1);
  assert.match(context.messages[0], /Restart the viewer server/);
});

test("a compatible server saves all input and output fields", async () => {
  const context = notebookContext();
  context.state.notebookCompatible = true;
  const fields = context.normalizeNotebookFields({input_background: "Black", output_background: "White"});
  context.state.drafts.set("a", {fields});
  let saved;
  context.changeAnnotations = async (ids, patch) => { saved = {ids, patch}; return true; };
  await context.saveNotebook("a");
  assert.equal(saved.ids[0], "a");
  assert.equal(saved.patch.fields.input_background, "Black");
  assert.equal(saved.patch.fields.output_background, "White");
  assert.equal(context.state.drafts.has("a"), false);
});

test("library counts include default statuses and overlapping problem sets", () => {
  const context = vm.createContext({
    REVIEW_STATUSES: ["Reviewed", "Awaiting Review", "Uncertain"],
    state: {problems: [{id: "a", sets: ["Training", "Milestones", "Training"]}, {id: "b", sets: ["Training"]}, {id: "c", sets: ["Evaluation"]}]},
    records: {a: {status: "Reviewed"}, c: {status: "Uncertain"}},
    annotation(id) { return context.records[id] || {status: "Awaiting Review"}; },
  });
  vm.runInContext(source.slice(source.indexOf("function libraryCounts()"), source.indexOf("function renderFilterCounts()")), context);
  let counts = context.libraryCounts();
  assert.deepEqual(JSON.parse(JSON.stringify(counts.statuses)), {Reviewed: 1, "Awaiting Review": 1, Uncertain: 1});
  assert.deepEqual(Object.fromEntries(counts.sets), {Evaluation: 1, Milestones: 1, Training: 2});
  context.records.b = {status: "Reviewed"};
  context.state.problems.push({id: "import", sets: ["Imported"]});
  counts = context.libraryCounts();
  assert.equal(counts.statuses.Reviewed, 2);
  assert.equal(counts.statuses["Awaiting Review"], 1);
  assert.equal(Object.fromEntries(counts.sets).Imported, 1);
});
