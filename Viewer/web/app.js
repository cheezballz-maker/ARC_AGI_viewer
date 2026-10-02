"use strict";

const $ = (id) => document.getElementById(id);
const COLORS = ["#000000", "#0074d9", "#ff4136", "#2ecc40", "#ffdc00", "#a0a0a0", "#f012be", "#ff851b", "#7fdbff", "#870c25"];
const REVIEW_STATUSES = ["Reviewed", "Awaiting Review", "Uncertain"];
const state = {problems: [], annotations: {}, current: null, task: null, filtered: [], section: "all", revealed: new Set(), drafts: new Map(), saveTimers: new Map(), saving: new Set(), saveFailures: new Set(), loadVersion: 0, notebookCompatible: false};
const token = document.querySelector('meta[name="workspace-token"]').content;
let noticeTimer;

function el(tag, className, text) {
  const node = document.createElement(tag);
  if (className) node.className = className;
  if (text !== undefined) node.textContent = text;
  return node;
}

function annotation(id) {
  return state.annotations[id] || {labels: [], notes: "", layers: [], fields: blankNotebookFields(), status: "Awaiting Review", starred: false, updated: ""};
}

async function api(path, data) {
  const response = await fetch(path, {method: data === undefined ? "GET" : "POST", headers: {"X-Workspace-Token": token, "Content-Type": "application/json"}, body: data === undefined ? undefined : JSON.stringify(data)});
  const result = await response.json();
  if (!response.ok) throw new Error(result.error || `Request failed (${response.status})`);
  return result;
}

function notify(message, error = false) {
  clearTimeout(noticeTimer);
  $("notification").textContent = message;
  $("notification").classList.toggle("error", error);
  $("notification").hidden = false;
  noticeTimer = setTimeout(() => { $("notification").hidden = true; }, error ? 8000 : 3500);
}

function showError(message, title = "Error") {
  $("error-title").textContent = title;
  $("error-message").textContent = message;
  if (!$("error-dialog").open) $("error-dialog").showModal();
}

function option(value, text = value) {
  const node = el("option", "", text);
  node.value = value;
  return node;
}

function libraryCounts() {
  const statuses = Object.fromEntries(REVIEW_STATUSES.map(status => [status, 0]));
  const sets = new Map();
  for (const problem of state.problems) {
    statuses[annotation(problem.id).status]++;
    for (const set of new Set(problem.sets)) sets.set(set, (sets.get(set) || 0) + 1);
  }
  return {statuses, sets: [...sets].sort(([a], [b]) => a.localeCompare(b))};
}

function renderFilterCounts() {
  const {statuses, sets} = libraryCounts();
  function render(containerId, filterId, items, allLabel) {
    const selected = $(filterId).value;
    const container = $(containerId);
    // Keep the buttons in place so keyboard focus survives filtering and saves.
    const values = ['', ...items.map(([value]) => value)];
    if (container.children.length !== values.length || values.some((value, index) => container.children[index].dataset.value !== value)) {
      container.replaceChildren(...values.map(value => {
        const button = el('button', 'library-filter');
        button.type = 'button';
        button.dataset.value = value;
        const name = el('span', 'filter-name');
        const count = el('span', 'filter-count');
        if (filterId === 'status-filter' && value) {
          const dot = el('span', 'row-dot');
          dot.dataset.status = value;
          button.append(dot);
        }
        button.append(name, count);
        button.addEventListener('click', () => { $(filterId).value = value; filterProblems(); });
        return button;
      }));
    }
    const counts = new Map([['', state.problems.length], ...items]);
    for (const button of container.children) {
      const value = button.dataset.value;
      button.querySelector('.filter-name').textContent = value || allLabel;
      button.querySelector('.filter-count').textContent = counts.get(value);
      button.setAttribute('aria-pressed', String(value === selected));
    }
  }
  render('status-counts', 'status-filter', Object.entries(statuses), 'All statuses');
  render('set-counts', 'set-filter', sets, 'All problem sets');
}

function filterProblems() {
  const query = $("search").value.trim().toLowerCase();
  const set = $("set-filter").value;
  const status = $("status-filter").value;
  const shape = $("shape-filter").value;
  state.filtered = state.problems.filter(problem => {
    const note = annotation(problem.id);
    const layerText = (note.layers || []).map(layer => `${layer.name} ${layer.observations}`).join(" ");
    const fieldText = Object.values(note.fields || {}).join(" ");
    return (!query || [problem.id, note.notes, layerText, fieldText].join(" ").toLowerCase().includes(query))
      && (!set || problem.sets.includes(set)) && (!status || note.status === status)
      && (!shape || problem.shape === shape)
      && (!$("star-filter").checked || note.starred)
      && (!$("notes-filter").checked || note.notes.trim() || layerText.trim() || fieldText.trim());
  });
  if ($("sort").value === "recent") state.filtered.sort((a, b) => annotation(b.id).updated.localeCompare(annotation(a.id).updated) || a.id.localeCompare(b.id));
  $("result-count").textContent = `${state.filtered.length} of ${state.problems.length}`;
  const extras = [$("star-filter").checked, $("notes-filter").checked, Boolean(shape)].filter(Boolean).length;
  $("extra-count").textContent = extras ? `(${extras})` : "";
  renderFilterCounts();
  renderLibrary();
  updateNavigation();
}

function renderLibrary() {
  const scrollTop = $("problem-list").scrollTop;
  const fragment = document.createDocumentFragment();
  for (const problem of state.filtered) {
    const note = annotation(problem.id);
    const row = el("div", `problem-row${state.current === problem.id ? " active" : ""}`);
    row.dataset.id = problem.id;
    const button = el("button", "problem-open");
    button.setAttribute("aria-label", `Open problem ${problem.id}`);
    if (state.current === problem.id) button.setAttribute("aria-current", "true");
    button.addEventListener("click", () => openProblem(problem.id));
    const thumbnail = el("canvas", "mini-grid");
    thumbnail.width = problem.thumbnail[0].length;
    thumbnail.height = problem.thumbnail.length;
    const ctx = thumbnail.getContext("2d");
    problem.thumbnail.forEach((cells, r) => cells.forEach((value, c) => {ctx.fillStyle = COLORS[value]; ctx.fillRect(c, r, 1, 1);}));
    thumbnail.setAttribute("aria-hidden", "true");
    const copy = el("span", "row-copy");
    copy.append(el("span", "row-title", problem.id), el("span", "row-subtitle", note.status));
    button.append(thumbnail, copy);
    const dot = el("span", "row-dot");
    dot.dataset.status = note.status;
    dot.title = note.status;
    row.append(button);
    if (note.starred) row.append(el("span", "row-star", "★"));
    row.append(dot);
    fragment.append(row);
  }
  if (!state.filtered.length) {
    const empty = el("div", "list-empty");
    empty.append(el("strong", "", "No matching problems"), el("p", "", "Try fewer filters or another search."));
    fragment.append(empty);
  }
  $("problem-list").replaceChildren(fragment);
  $("problem-list").scrollTop = scrollTop;
}

function updateNavigation() {
  const index = state.filtered.findIndex(item => item.id === state.current);
  $("position").textContent = index >= 0 ? `${index + 1} / ${state.filtered.length}` : state.current ? "Outside filters" : "";
  $("previous").disabled = index <= 0;
  $("next").disabled = !state.filtered.length || index >= state.filtered.length - 1;
}

async function openProblem(id) {
  if (state.current === id && state.task) return;
  const version = ++state.loadVersion;
  if (state.current) saveNotebook(state.current);
  try {
    const task = await api(`/api/problem?id=${encodeURIComponent(id)}`);
    if (version !== state.loadVersion) return;
    state.current = id;
    state.task = task;
    state.revealed.clear();
    history.replaceState(null, "", `#${encodeURIComponent(id)}`);
    document.title = `${id} · ARC Fieldnotes`;
    const problem = state.problems.find(item => item.id === id);
    $("problem-id").textContent = id;
    $("problem-sets").textContent = problem.sets.join(" / ");
    $("problem-meta").textContent = `${task.train.length} training pairs  ·  ${task.test.length} test${task.test.length === 1 ? "" : "s"}  ·  ${problem.shape.toLowerCase()}`;
    $("empty-study").hidden = true;
    $("problem-workspace").hidden = false;
    $("notebook-content").hidden = false;
    $("notebook-empty").hidden = true;
    $("notebook-id").textContent = id;
    for (const control of document.querySelectorAll("[data-notebook-field]")) {
      control.value = state.drafts.get(id)?.fields?.[control.dataset.notebookField] ?? annotation(id).fields?.[control.dataset.notebookField] ?? "";
    }
    renderNotebook();
    renderExamples();
    renderLibrary();
    updateNavigation();
    $("study").scrollTop = 0;
    document.querySelector('.problem-row.active')?.scrollIntoView({block: "nearest"});
  } catch (error) {showError(error.message, "Could not open problem");}
}

function renderNotebook() {
  if (!state.current) return;
  const note = annotation(state.current);
  $("review-status").value = state.drafts.get(state.current)?.status ?? note.status;
  $("bookmark").textContent = note.starred ? "★" : "☆";
  $("bookmark").setAttribute("aria-pressed", String(note.starred));
  $("bookmark").setAttribute("aria-label", note.starred ? "Remove bookmark" : "Bookmark problem");
  updateSaveState();
}

async function changeAnnotations(ids, patch) {
  try {
    const changes = await api("/api/annotate", {ids, patch});
    for (const [id, value] of Object.entries(changes)) {
      // Responses may arrive out of order. Keep the newest committed record.
      if (!state.annotations[id] || value.updated >= state.annotations[id].updated) state.annotations[id] = value;
    }
    filterProblems();
    renderNotebook();
    return true;
  } catch (error) {
    notify(error.message, true);
    renderNotebook();
    return false;
  }
}

function updateSaveState() {
  const id = state.current;
  $("save-state").textContent = state.saving.has(id) ? "Saving…" : state.saveFailures.has(id) ? "Not saved · retry" : state.drafts.has(id) ? "Unsaved changes" : "Saved";
  $("save-state").classList.toggle("error", state.saveFailures.has(id));
}

async function saveNotebook(id) {
  clearTimeout(state.saveTimers.get(id));
  if (!state.drafts.has(id) || state.saving.has(id)) return;
  if (!state.notebookCompatible) {
    if (!state.saveFailures.has(id)) notify("Restart the viewer server to save the updated notebook form. Your draft is retained; export all notebooks before restarting.", true);
    state.saveFailures.add(id);
    updateSaveState();
    return;
  }
  const patch = structuredClone(state.drafts.get(id));
  state.saving.add(id);
  updateSaveState();
  const saved = await changeAnnotations([id], patch);
  state.saving.delete(id);
  if (saved) {
    state.saveFailures.delete(id);
    const remaining = {...state.drafts.get(id)};
    for (const [key, value] of Object.entries(patch)) {
      if (JSON.stringify(remaining[key]) === JSON.stringify(value)) delete remaining[key];
    }
    if (Object.keys(remaining).length) state.drafts.set(id, remaining);
    else state.drafts.delete(id);
  } else state.saveFailures.add(id);
  updateSaveState();
  if (saved && state.drafts.has(id)) saveNotebook(id);
}

function queueDraft(id, patch) {
  state.drafts.set(id, {...state.drafts.get(id), ...structuredClone(patch)});
  clearTimeout(state.saveTimers.get(id));
  state.saveTimers.set(id, setTimeout(() => saveNotebook(id), 650));
  updateSaveState();
}

function blankNotebookFields() {
  return {input_background: "", output_background: "", input_objects: "", output_objects: "", input_object_relationships: "", output_object_relationships: "", transformations: "", strategy: ""};
}

function normalizeNotebookFields(fields = {}) {
  const result = blankNotebookFields();
  for (const key of Object.keys(result)) {
    const legacy = key.startsWith("input_") ? key.slice(6) : key;
    result[key] = fields[key] ?? fields[legacy] ?? "";
  }
  return result;
}

function exportRecord(id) {
  const problem = state.problems.find(item => item.id === id);
  return {...annotation(id), ...state.drafts.get(id), metadata: problem?.metadata ?? annotation(id).metadata ?? null};
}

function downloadNotebook(problems, filename) {
  const url = URL.createObjectURL(new Blob([JSON.stringify({version: 5, problems}, null, 2)], {type: "application/json"}));
  const link = el("a");
  link.href = url;
  link.download = filename;
  link.click();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}

function renderExamples() {
  resizeObserver.disconnect();
  $("examples").replaceChildren();
  if (!state.task) return;
  for (const section of ["train", "test"]) {
    if (state.section !== "all" && state.section !== section) continue;
    const pairs = state.task[section];
    const heading = el("div", "section-heading");
    heading.append(el("h2", "", section === "train" ? "Training" : "Test"), el("span", "", `${pairs.length} example${pairs.length === 1 ? "" : "s"}`));
    $("examples").append(heading);
    const grid = el("div", "example-grid");
    if (!pairs.length) grid.append(el("p", "list-empty", "No examples in this section."));
    pairs.forEach((pair, index) => {
      const key = `${section}:${index}`;
      const card = el("article", "example-card");
      card.dataset.example = key;
      const header = el("div", "card-header");
      header.append(el("strong", "", `${section === "train" ? "TRAINING" : "TEST"}  ${String(index + 1).padStart(2, "0")}`));
      if (section === "test" && pair.output && state.revealed.has(key)) {
        const hide = el("button", "hide-answer", "Hide answer");
        hide.addEventListener("click", () => {state.revealed.delete(key); renderExamples();});
        header.append(hide);
      }
      const viewport = el("div", "pair-viewport");
      const row = el("div", "grid-pair");
      const showOutput = pair.output && (section === "train" || state.revealed.has(key));
      row.append(gridView(pair.input, "Input"), el("span", "pair-arrow", "→"));
      if (showOutput) row.append(gridView(pair.output, "Output"));
      else {
        const placeholder = el("div", "answer-placeholder");
        if (pair.output) {
          const reveal = el("button", "", "Reveal answer");
          reveal.addEventListener("click", () => {state.revealed.add(key); renderExamples();});
          placeholder.append(reveal);
        } else placeholder.append(el("span", "", "No reference output"));
        row.append(placeholder);
      }
      viewport.append(row);
      card.append(header, viewport);
      grid.append(card);
      card._pair = {input: pair.input, output: showOutput ? pair.output : null};
      resizeObserver.observe(card);
    });
    $("examples").append(grid);
  }
  requestAnimationFrame(drawAllGrids);
}

function gridView(grid, title) {
  const wrapper = el("div", "grid-wrapper");
  const caption = el("div", "grid-caption");
  caption.append(el("strong", "", title), el("span", "", `${grid.length} × ${grid[0].length}`));
  const canvas = el("canvas", "grid-canvas");
  canvas.dataset.grid = title.toLowerCase();
  canvas._grid = grid;
  canvas.setAttribute("role", "img");
  canvas.setAttribute("aria-label", `${title} grid, ${grid.length} rows and ${grid[0].length} columns`);
  canvas.addEventListener("mousemove", event => {
    const bounds = canvas.getBoundingClientRect();
    const c = Math.floor((event.clientX - bounds.left - 1) / canvas._cell);
    const r = Math.floor((event.clientY - bounds.top - 1) / canvas._cell);
    if (r >= 0 && r < grid.length && c >= 0 && c < grid[0].length) $("cell-details").textContent = `${title} · Row ${r + 1}, column ${c + 1} · Color ${grid[r][c]}`;
  });
  canvas.addEventListener("mouseleave", () => {$("cell-details").textContent = "";});
  wrapper.append(caption, canvas);
  return wrapper;
}

function drawAllGrids() {
  for (const card of document.querySelectorAll(".example-card")) drawCard(card);
}

function drawCard(card) {
  if (!card.isConnected) return;
  const {input, output} = card._pair;
  const width = card.clientWidth;
  const totalCols = input[0].length + (output ? output[0].length : 0);
  const reserve = output ? 88 : 228;
  const maxRows = Math.max(input.length, output?.length || 0);
  const cell = Math.max(3, Math.min(26, Math.floor((width - reserve) / totalCols), Math.floor(310 / maxRows)));
  for (const canvas of card.querySelectorAll(".grid-canvas")) drawGrid(canvas, cell);
}

function drawGrid(canvas, cell) {
  const grid = canvas._grid;
  const width = grid[0].length * cell;
  const height = grid.length * cell;
  const ratio = window.devicePixelRatio || 1;
  canvas.width = Math.round(width * ratio);
  canvas.height = Math.round(height * ratio);
  canvas.style.width = `${width + 2}px`;
  canvas.style.height = `${height + 2}px`;
  canvas._cell = cell;
  const context = canvas.getContext("2d");
  context.scale(ratio, ratio);
  grid.forEach((row, r) => row.forEach((value, c) => {
    context.fillStyle = COLORS[value];
    context.fillRect(c * cell, r * cell, cell, cell);
    if (cell >= 7) {
      context.strokeStyle = "rgba(130,145,150,.32)";
      context.lineWidth = .65;
      context.strokeRect(c * cell + .3, r * cell + .3, cell, cell);
    }
    if ($("cell-values").checked && cell >= 12) {
      context.fillStyle = [0, 1, 2, 6, 9].includes(value) ? "#fff" : "#172419";
      context.textAlign = "center";
      context.textBaseline = "middle";
      context.font = `${Math.max(8, Math.min(12, cell * .43))}px Segoe UI`;
      context.fillText(String(value), c * cell + cell / 2, r * cell + cell / 2);
    }
  }));
}

const resizeObserver = new ResizeObserver(entries => entries.forEach(entry => drawCard(entry.target)));

async function loadLibrary(openInitial = false) {
  const result = await api("/api/library");
  state.problems = result.problems;
  const expectedFields = Object.keys(blankNotebookFields());
  state.notebookCompatible = Array.isArray(result.notebook_fields)
    && result.notebook_fields.length === expectedFields.length
    && expectedFields.every(key => result.notebook_fields.includes(key))
    && Array.isArray(result.review_statuses)
    && result.review_statuses.length === REVIEW_STATUSES.length
    && REVIEW_STATUSES.every(status => result.review_statuses.includes(status));
  const legacyStatuses = {Unreviewed: "Awaiting Review", Investigating: "Uncertain", Understood: "Reviewed"};
  state.annotations = Object.fromEntries(Object.entries(result.annotations).map(([id, record]) => [id, {...record, status: legacyStatuses[record.status] ?? record.status ?? "Awaiting Review", fields: normalizeNotebookFields(record.fields)}]));
  $("total-count").textContent = state.problems.length;
  filterProblems();
  if (openInitial) {
    const requested = decodeURIComponent(location.hash.slice(1));
    const initial = state.problems.find(item => item.id === requested) || state.problems[0];
    if (initial) await openProblem(initial.id);
    if (result.migrated) notify("Existing labels migrated.");
    if (result.warnings.length) showError(result.warnings.join("\n"), "Some files could not be loaded");
  }
}

async function importFiles(files) {
  const jsonFiles = [...files].filter(file => file.name.toLowerCase().endsWith(".json"));
  if (!jsonFiles.length) {notify("Choose JSON files or a folder containing ARC problems.", true); return;}
  const errors = [];
  let first;
  let imported = 0;
  $("import-files").disabled = $("import-folder").disabled = true;
  for (const file of jsonFiles) {
    try {
      if (file.size > 3_000_000) throw new Error("File is too large (3 MB maximum).");
      const result = await api("/api/import", {filename: file.name, task: JSON.parse((await file.text()).replace(/^\uFEFF/, ""))});
      first ||= result.id;
      imported++;
    } catch (error) {errors.push(`${file.name}: ${error.message}`);}
  }
  try {
    await loadLibrary();
    if (first) await openProblem(first);
    notify(`${imported} problem files opened.`);
    if (errors.length) showError(errors.join("\n"), "Some files could not be imported");
  } catch (error) {showError(error.message);}
  finally {$("import-files").disabled = $("import-folder").disabled = false;}
}

$("search").addEventListener("input", filterProblems);
for (const id of ["shape-filter", "star-filter", "notes-filter", "sort"]) $(id).addEventListener("change", filterProblems);
$("reset-filters").addEventListener("click", () => {
  for (const id of ["search", "set-filter", "status-filter", "shape-filter"]) $(id).value = "";
  for (const id of ["star-filter", "notes-filter"]) $(id).checked = false;
  filterProblems();
});
$("bookmark").addEventListener("click", () => {if (state.current) changeAnnotations([state.current], {starred: !annotation(state.current).starred});});
$("review-status").addEventListener("change", () => {
  if (state.current) {
    queueDraft(state.current, {status: $("review-status").value});
    saveNotebook(state.current);
  }
});
for (const control of document.querySelectorAll("[data-notebook-field]")) {
  control.addEventListener("input", () => {
    const id = state.current;
    if (!id) return;
    const fields = normalizeNotebookFields({...annotation(id).fields, ...state.drafts.get(id)?.fields});
    fields[control.dataset.notebookField] = control.value;
    queueDraft(id, {fields});
  });
  control.addEventListener("blur", () => { if (state.current) saveNotebook(state.current); });
}
$("save-notes").addEventListener("click", () => {if (state.current) saveNotebook(state.current);});
window.addEventListener("beforeunload", event => {if (state.drafts.size || state.saving.size) {event.preventDefault(); event.returnValue = "";}});
for (const button of document.querySelectorAll("[data-section]")) button.addEventListener("click", () => {
  state.section = button.dataset.section;
  document.querySelectorAll("[data-section]").forEach(tab => tab.setAttribute("aria-selected", String(tab === button)));
  renderExamples();
});
$("cell-values").addEventListener("change", drawAllGrids);
function navigate(step) {
  const index = state.filtered.findIndex(item => item.id === state.current);
  const next = state.filtered[index + step];
  if (next) openProblem(next.id);
}
$("previous").addEventListener("click", () => navigate(-1));
$("next").addEventListener("click", () => navigate(1));
$("toggle-notebook").addEventListener("click", () => $("notebook").classList.toggle("open"));
$("close-notebook").addEventListener("click", () => $("notebook").classList.remove("open"));
$("import-files").addEventListener("click", () => $("file-input").click());
$("import-folder").addEventListener("click", () => $("folder-input").click());
for (const id of ["file-input", "folder-input"]) $(id).addEventListener("change", async () => {await importFiles($(id).files); $(id).value = "";});
$("dismiss-error").addEventListener("click", () => $("error-dialog").close());
$("export-problem").addEventListener("click", () => {
  if (state.current) downloadNotebook({[state.current]: exportRecord(state.current)}, `${state.current}-notebook.json`);
});
$("export-notes").addEventListener("click", () => {
  const ids = new Set([...Object.keys(state.annotations), ...state.drafts.keys()]);
  downloadNotebook(Object.fromEntries([...ids].map(id => [id, exportRecord(id)])), "arc-fieldnotes.json");
});
document.addEventListener("keydown", event => {
  const typing = ["INPUT", "TEXTAREA", "SELECT"].includes(document.activeElement.tagName);
  if (event.key === "/" && !typing) {event.preventDefault(); $("search").focus();}
  if (event.altKey && event.key === "ArrowLeft") {event.preventDefault(); navigate(-1);}
  if (event.altKey && event.key === "ArrowRight") {event.preventDefault(); navigate(1);}
  if ((event.ctrlKey || event.metaKey) && event.key === "s") {event.preventDefault(); if (state.current) saveNotebook(state.current);}
  if (event.key === "Escape") $("notebook").classList.remove("open");
});
function initPanelResizing() {
  const workspace = document.querySelector(".workspace");
  const storageKey = "arc-fieldnotes-panel-widths";
  const preferred = {};
  let widths, drag;
  try {
    const saved = JSON.parse(localStorage.getItem(storageKey));
    for (const side of ["library", "notebook"]) {
      if (typeof saved?.[side] === "number" && Number.isFinite(saved[side])) preferred[side] = saved[side];
    }
  } catch { /* Resizing remains available when browser storage is disabled. */ }
  const clamp = (value, min, max) => Math.min(max, Math.max(min, value));
  function dimensions() {
    const width = workspace.clientWidth;
    const docked = window.innerWidth > 1170;
    const minimum = {library: window.innerWidth <= 720 ? 180 : 220, notebook: Math.min(280, width - 24)};
    const defaults = {library: window.innerWidth >= 1600 ? 292 : docked ? 272 : window.innerWidth <= 720 ? 205 : 250, notebook: docked && window.innerWidth < 1600 ? 360 : 380};
    const budget = Math.max(minimum.library, width - (docked ? 390 + 12 : Math.min(240, width * .45) + 6));
    return {width, docked, minimum, defaults, budget};
  }
  function limits(side) {
    const d = dimensions();
    const maximum = side === "library" ? Math.min(520, d.budget - (d.docked ? widths.notebook : 0)) : Math.min(720, d.docked ? d.budget - widths.library : d.width - 24);
    return [d.minimum[side], Math.max(d.minimum[side], maximum)];
  }
  function layout() {
    const d = dimensions();
    widths = {
      library: clamp(preferred.library ?? d.defaults.library, d.minimum.library, Math.max(d.minimum.library, Math.min(520, d.budget - (d.docked ? d.minimum.notebook : 0)))),
      notebook: clamp(preferred.notebook ?? d.defaults.notebook, d.minimum.notebook, Math.max(d.minimum.notebook, Math.min(720, d.docked ? d.budget - d.minimum.library : d.width - 24))),
    };
    if (d.docked && widths.library + widths.notebook > d.budget) {
      const excess = widths.library + widths.notebook - d.budget;
      const flexible = widths.library + widths.notebook - d.minimum.library - d.minimum.notebook;
      for (const side of ["library", "notebook"]) widths[side] -= excess * (widths[side] - d.minimum[side]) / flexible;
    }
    for (const side of ["library", "notebook"]) {
      widths[side] = Math.round(widths[side]);
      workspace.style.setProperty(`--${side}-width`, `${widths[side]}px`);
      const handle = $(`resize-${side}`);
      const [min, max] = limits(side);
      handle.setAttribute("aria-valuemin", Math.round(min));
      handle.setAttribute("aria-valuemax", Math.round(max));
      handle.setAttribute("aria-valuenow", widths[side]);
      handle.setAttribute("aria-valuetext", `${widths[side]} pixels`);
    }
  }
  function persist() {
    try { localStorage.setItem(storageKey, JSON.stringify(preferred)); } catch { /* Session-only preference. */ }
  }
  function resize(side, value) {
    const [min, max] = limits(side);
    // Use visible widths so expanding one side never unexpectedly moves the other.
    Object.assign(preferred, widths, {[side]: clamp(value, min, max)});
    layout();
  }
  function finish() {
    if (!drag) return;
    const {handle, pointerId} = drag;
    drag = null;
    if (handle.hasPointerCapture(pointerId)) handle.releasePointerCapture(pointerId);
    handle.classList.remove("dragging");
    document.body.classList.remove("resizing-panels");
    persist();
  }
  for (const side of ["library", "notebook"]) {
    const handle = $(`resize-${side}`);
    handle.addEventListener("pointerdown", event => {
      if (event.button !== 0 || drag) return;
      event.preventDefault();
      handle.focus();
      drag = {handle, pointerId: event.pointerId, x: event.clientX, width: widths[side]};
      handle.setPointerCapture(event.pointerId);
      handle.classList.add("dragging");
      document.body.classList.add("resizing-panels");
    });
    handle.addEventListener("pointermove", event => {
      if (drag?.handle !== handle || drag.pointerId !== event.pointerId) return;
      resize(side, drag.width + (event.clientX - drag.x) * (side === "library" ? 1 : -1));
    });
    for (const event of ["pointerup", "pointercancel", "lostpointercapture"]) handle.addEventListener(event, finish);
    function reset() { delete preferred[side]; layout(); persist(); }
    handle.addEventListener("dblclick", reset);
    handle.addEventListener("keydown", event => {
      if (!["ArrowLeft", "ArrowRight", "Home", "End", "Enter"].includes(event.key)) return;
      event.preventDefault();
      if (event.key === "Enter") { reset(); return; }
      const [min, max] = limits(side);
      const delta = (event.key === "ArrowLeft" ? -1 : 1) * (side === "library" ? 1 : -1) * (event.shiftKey ? 40 : 10);
      resize(side, event.key === "Home" ? min : event.key === "End" ? max : widths[side] + delta);
      persist();
    });
  }
  window.addEventListener("blur", finish);
  window.addEventListener("resize", () => { finish(); layout(); });
  layout();
}
initPanelResizing();
loadLibrary(true).catch(error => showError(error.message, "Could not load workspace"));
