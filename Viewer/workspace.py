"""Problem catalog and durable, problem-level research annotations."""

from __future__ import annotations

import copy
import json
import re
import tempfile
import threading
from datetime import datetime, timezone
from pathlib import Path

if __package__:
    from .solution import validate_solution
else:
    from solution import validate_solution

BASE = Path(__file__).resolve().parent
REPO = BASE.parent
STATUSES = ("Reviewed", "Awaiting Review", "Uncertain")
LEGACY_STATUSES = {"Unreviewed": "Awaiting Review", "Investigating": "Uncertain", "Understood": "Reviewed"}
LEGACY_NOTEBOOK_FIELDS = ("background", "objects", "object_relationships", "transformations", "strategy")
NOTEBOOK_FIELDS = ("input_background", "output_background", "input_objects", "output_objects",
                   "input_object_relationships", "output_object_relationships", "transformations", "strategy")


def grid_size(grid: list) -> tuple[int, int]:
    if not isinstance(grid, list) or not grid or not all(isinstance(row, list) and row for row in grid):
        raise ValueError("A grid must contain non-empty rows.")
    if len({len(row) for row in grid}) != 1:
        raise ValueError("Grid rows must have the same length.")
    if max(len(grid), len(grid[0])) > 100:
        raise ValueError("Grids larger than 100 × 100 are not supported.")
    if any(type(cell) is not int or not 0 <= cell <= 9 for row in grid for cell in row):
        raise ValueError("Grid cells must be integers from 0 to 9.")
    return len(grid), len(grid[0])


def validate_task(task: dict) -> dict:
    if not isinstance(task, dict) or any(not isinstance(task.get(key), list) for key in ("train", "test")):
        raise ValueError("Expected an ARC problem with training and test examples.")
    for section in ("train", "test"):
        for index, example in enumerate(task[section], 1):
            if not isinstance(example, dict) or "input" not in example:
                raise ValueError(f"{section} {index}: missing input.")
            if section == "train" and "output" not in example:
                raise ValueError(f"{section} {index}: missing output.")
            for name in ("input", "output"):
                if name in example:
                    grid_size(example[name])
    return task


def load_task(path: Path) -> dict:
    return validate_task(json.loads(path.read_text(encoding="utf-8-sig")))


def atomic_json(path: Path, value: dict) -> None:
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=path.parent, suffix=".tmp", delete=False) as stream:
            temporary = Path(stream.name)
            json.dump(value, stream, indent=2, ensure_ascii=False)
            stream.write("\n")
        temporary.replace(path)
    finally:
        if temporary and temporary.exists():
            temporary.unlink()


def blank_annotation() -> dict:
    return {"labels": [], "notes": "", "layers": [], "fields": dict.fromkeys(NOTEBOOK_FIELDS, ""), "metadata": None, "status": "Awaiting Review", "starred": False, "updated": ""}


def validate_layers(layers: list) -> list[dict]:
    """Layer order defines depth; references may only point to earlier layers."""
    if not isinstance(layers, list) or len(layers) > 50:
        raise ValueError("Provide at most 50 observation layers per problem.")
    result, earlier_ids = [], set()
    for layer in layers:
        if not isinstance(layer, dict) or set(layer) != {"id", "name", "observations", "built_from", "evidence"}:
            raise ValueError("Each layer needs an ID, name, observations, built_from, and evidence.")
        identifier = layer["id"]
        if not isinstance(identifier, str) or not re.fullmatch(r"[A-Za-z0-9_-]{1,80}", identifier) or identifier in earlier_ids:
            raise ValueError("Layer IDs must be unique, stable identifiers.")
        if not isinstance(layer["name"], str) or len(layer["name"]) > 120:
            raise ValueError("Layer names must be text, up to 120 characters.")
        if not isinstance(layer["observations"], str) or len(layer["observations"]) > 20_000:
            raise ValueError("Layer observations must be text, up to 20,000 characters.")
        dependencies = layer["built_from"]
        if not isinstance(dependencies, list) or any(not isinstance(key, str) or key not in earlier_ids for key in dependencies):
            raise ValueError("Built-from links must reference earlier layers in this problem.")
        evidence = layer["evidence"]
        if not isinstance(evidence, list) or len(evidence) > 200:
            raise ValueError("Provide at most 200 evidence links per layer.")
        links = []
        for link in evidence:
            if (not isinstance(link, dict) or set(link) != {"section", "index", "grid"}
                    or link["section"] not in ("train", "test")
                    or type(link["index"]) is not int or link["index"] < 0
                    or link["grid"] not in ("input", "output")):
                raise ValueError("Evidence must reference a training/test example and its input/output grid.")
            if link not in links:
                links.append(copy.deepcopy(link))
        result.append({**layer, "built_from": list(dict.fromkeys(dependencies)), "evidence": links})
        earlier_ids.add(identifier)
    return result


def validate_evidence(layers: list, task: dict) -> None:
    """Only link to grids that actually exist in the selected problem."""
    for layer in validate_layers(layers):
        for link in layer["evidence"]:
            examples = task[link["section"]]
            if link["index"] >= len(examples) or link["grid"] not in examples[link["index"]]:
                raise ValueError("An evidence link points to a grid that is not in this problem.")


def clean_labels(labels: list) -> list[str]:
    if not isinstance(labels, list) or len(labels) > 100:
        raise ValueError("Provide at most 100 labels per problem.")
    unique = {}
    for label in labels:
        if not isinstance(label, str) or not 0 < len(label.strip()) <= 80:
            raise ValueError("Labels must contain 1–80 characters.")
        unique.setdefault(label.strip().casefold(), label.strip())
    return sorted(unique.values(), key=str.casefold)


def validate_annotation(value: dict) -> dict:
    if not isinstance(value, dict):
        raise ValueError("Invalid problem annotation.")
    result = blank_annotation() | value
    result["labels"] = clean_labels(result["labels"])
    result["layers"] = validate_layers(result["layers"])
    if "solution" in result:
        result["solution"] = validate_solution(result["solution"])
    fields = result["fields"]
    if not isinstance(fields, dict) or set(fields) != set(NOTEBOOK_FIELDS):
        raise ValueError("Notebook field names do not match the Input/Output form. Restart the viewer server and refresh the page.")
    if any(not isinstance(text, str) or len(text) > 20_000 for text in fields.values()):
        raise ValueError("Notebook fields must contain text, up to 20,000 characters each.")
    if result["metadata"] is not None and not isinstance(result["metadata"], dict):
        raise ValueError("Invalid problem metadata.")
    if not isinstance(result["notes"], str) or len(result["notes"]) > 100_000:
        raise ValueError("Notes must be text, up to 100,000 characters.")
    if result["status"] not in STATUSES or type(result["starred"]) is not bool:
        raise ValueError("Invalid review status or bookmark.")
    if not isinstance(result["updated"], str):
        raise ValueError("Invalid annotation timestamp.")
    keys = list(blank_annotation()) + (["solution"] if "solution" in result else [])
    return {key: result[key] for key in keys}


class Notebook:
    def __init__(self, path: Path = BASE / "problem_annotations.json", legacy: Path | None = BASE / "example_labels.json"):
        self.path = path
        self.lock = threading.RLock()
        self.data: dict[str, dict] = {}
        self.migrated = False
        if path.exists():
            document = json.loads(path.read_text(encoding="utf-8"))
            if not isinstance(document, dict) or document.get("version") not in (1, 2, 3, 4, 5) or not isinstance(document.get("problems"), dict):
                raise ValueError(f"Invalid notebook file: {path}. The original file has been preserved.")
            for key, value in document["problems"].items():
                if isinstance(value, dict) and isinstance(value.get("status"), str):
                    value = value | {"status": LEGACY_STATUSES.get(value["status"], value["status"])}
                if document["version"] < 5 and isinstance(value, dict) and "fields" in value:
                    fields = value["fields"]
                    if not isinstance(fields, dict) or set(fields) != set(LEGACY_NOTEBOOK_FIELDS):
                        raise ValueError("Invalid legacy notebook fields. The original file has been preserved.")
                    # Preserve earlier observations as input notes; output starts blank.
                    fields = {("input_" + name if name in LEGACY_NOTEBOOK_FIELDS[:3] else name): text
                              for name, text in fields.items()}
                    value = value | {"fields": dict.fromkeys(NOTEBOOK_FIELDS, "") | fields}
                self.data[key] = validate_annotation(value)
        elif legacy and legacy.exists():
            old = json.loads(legacy.read_text(encoding="utf-8"))
            if not isinstance(old, dict):
                raise ValueError("Invalid legacy labels. The original file has been preserved.")
            for filename, examples in old.items():
                if not isinstance(examples, dict):
                    raise ValueError("Invalid legacy labels. The original file has been preserved.")
                problem_id = Path(filename.replace("\\", "/")).stem
                record = self.data.setdefault(problem_id, blank_annotation())
                for labels in examples.values():
                    record["labels"] = clean_labels(record["labels"] + clean_labels(labels))
            self._write(self.data)
            self.migrated = True

    def _write(self, data: dict) -> None:
        atomic_json(self.path, {"version": 5, "problems": data})

    def snapshot(self) -> dict:
        with self.lock:
            return copy.deepcopy(self.data)

    def update(self, ids: list[str], patch: dict, metadata: dict | None = None) -> dict:
        if not isinstance(patch, dict) or set(patch) - {"fields", "labels", "notes", "layers", "solution", "status", "starred", "add_label", "remove_label"}:
            raise ValueError("Unknown notebook field.")
        with self.lock:
            updated = copy.deepcopy(self.data)
            for problem_id in ids:
                record = updated.get(problem_id, blank_annotation()) | {key: value for key, value in patch.items() if key not in ("add_label", "remove_label")}
                if "add_label" in patch:
                    record["labels"] = clean_labels(record["labels"] + [patch["add_label"]])
                if "remove_label" in patch:
                    label = clean_labels([patch["remove_label"]])[0]
                    record["labels"] = [name for name in record["labels"] if name.casefold() != label.casefold()]
                record["updated"] = datetime.now(timezone.utc).isoformat()
                if metadata is not None:
                    record["metadata"] = copy.deepcopy(metadata[problem_id])
                updated[problem_id] = validate_annotation(record)
            self._write(updated)
            self.data = updated
            return {problem_id: copy.deepcopy(updated[problem_id]) for problem_id in ids}


class Catalog:
    def __init__(self, start: Path | None = None, imports: Path = BASE / "imports"):
        self.problems: dict[str, dict] = {}
        self.warnings: list[str] = []
        self.imports = imports
        self.lock = threading.RLock()
        roots = [
            (REPO / "ARC-AGI-master" / "ARC-AGI-master" / "data" / "training", "ARC · Training"),
            (REPO / "ARC-AGI-master" / "ARC-AGI-master" / "data" / "evaluation", "ARC · Evaluation"),
            (REPO / "ArcAgi-StarterCode_v1.4.0.1" / "Milestones", "Milestones"),
        ] if start is None else [(start.resolve(), start.name)]
        roots.append((imports, "Imported"))
        for root, name in roots:
            paths = [root] if root.is_file() else sorted(root.rglob("*.json")) if root.exists() else []
            for path in paths:
                group = name
                if root.is_dir() and path.parent != root:
                    group += " / " + path.parent.relative_to(root).as_posix()
                try:
                    self.add(path.stem, load_task(path), group)
                except (OSError, ValueError) as exc:
                    self.warnings.append(f"{path.name}: {exc}")

    def add(self, problem_id: str, task: dict, source: str) -> None:
        existing = self.problems.get(problem_id)
        if existing:
            if source not in existing["sets"]:
                existing["sets"].append(source)
            # Dataset copies share an ID. Prefer the copy with more reference outputs.
            if sum("output" in item for item in task["test"]) > sum("output" in item for item in existing["task"]["test"]):
                existing["task"] = task
            return
        pairs = task["train"]
        shape_changes = any(grid_size(pair["input"]) != grid_size(pair["output"]) for pair in pairs)
        self.problems[problem_id] = {
            "id": problem_id, "sets": [source], "task": task,
            "train_count": len(pairs), "test_count": len(task["test"]),
            "shape": "Changes size" if shape_changes else "Same size",
            "thumbnail": pairs[0]["input"] if pairs else task["test"][0]["input"] if task["test"] else [[0]],
        }

    def index(self) -> list[dict]:
        with self.lock:
            return [{**{key: copy.deepcopy(value) for key, value in item.items() if key != "task"}, "metadata": self.metadata(item["id"])} for item in sorted(self.problems.values(), key=lambda item: item["id"])]

    def metadata(self, problem_id: str) -> dict:
        with self.lock:
            problem = self.problems[problem_id]
            return {"problem_id": problem_id, "problem_sets": list(problem["sets"]),
                    "training_examples": problem["train_count"], "test_examples": problem["test_count"],
                    "changes_grid_size": problem["shape"] == "Changes size"}

    def import_task(self, filename: str, task: dict) -> str:
        task = validate_task(task)
        relative = Path(filename.replace("\\", "/"))
        problem_id = relative.stem
        if not re.fullmatch(r"[a-zA-Z0-9_-]{1,100}", problem_id):
            raise ValueError("Task filenames may contain letters, numbers, underscores, or hyphens.")
        with self.lock:
            if problem_id in self.problems:
                # Never silently replace an existing problem with unrelated uploaded data.
                if self.problems[problem_id]["task"] != task:
                    raise ValueError(f"{problem_id} already exists with different examples. Rename the file to import it separately.")
                return problem_id
            self.imports.mkdir(parents=True, exist_ok=True)
            atomic_json(self.imports / f"{problem_id}.json", task)
            self.add(problem_id, task, "Imported")
            return problem_id
