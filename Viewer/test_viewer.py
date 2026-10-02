"""Run: python -m unittest discover -s Viewer -v."""

import copy
import json
import re
import tempfile
import threading
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from unittest.mock import patch
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from solution import blank_solution, validate_solution
from server import create_server
from workspace import Catalog, Notebook, NOTEBOOK_FIELDS, STATUSES, grid_size, load_task, validate_task, validate_layers, validate_evidence

TASK = {"train": [{"input": [[1, 2]], "output": [[2], [1]]}], "test": [{"input": [[0]]}]}
LAYERS = [
    {"id": "direct", "name": "Direct observations", "observations": "Two colored cells.", "built_from": [],
     "evidence": [{"section": "train", "index": 0, "grid": "input"}]},
    {"id": "objects", "name": "Objects", "observations": "One connected object.", "built_from": ["direct"],
     "evidence": [{"section": "train", "index": 0, "grid": "output"}]},
]


class NotebookTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name)
        self.path = self.root / "notebook.json"
        self.book = Notebook(self.path, legacy=None)

    def test_problem_labels_bulk_edit_and_restart(self):
        self.book.update(["1cf80156", "abc12345"], {"add_label": " extraction "})
        self.book.update(["1cf80156"], {"add_label": "Extraction"})
        self.book.update(["1cf80156"], {"notes": "Keep the object's bounding box.", "status": "Reviewed", "starred": True})
        record = Notebook(self.path, legacy=None).snapshot()["1cf80156"]
        self.assertEqual(record["labels"], ["extraction"])
        self.assertEqual(record["notes"], "Keep the object's bounding box.")
        self.assertTrue(record["starred"])
        self.book.update(["1cf80156"], {"remove_label": "EXTRACTION"})
        self.assertEqual(self.book.snapshot()["1cf80156"]["labels"], [])
        self.assertEqual(self.book.snapshot()["abc12345"]["labels"], ["extraction"])

    def test_migration_unions_labels_across_pairs_and_copies(self):
        legacy = self.root / "legacy.json"
        old = {"Milestones/B/1cf80156.json": {"train:0": ["crop"], "test:0": ["objects"]}, "data\\training\\1cf80156.json": {"train:1": ["crop"]}}
        legacy.write_text(json.dumps(old), encoding="utf-8")
        book = Notebook(self.path, legacy)
        self.assertTrue(book.migrated)
        self.assertEqual(book.snapshot()["1cf80156"]["labels"], ["crop", "objects"])
        self.assertEqual(json.loads(legacy.read_text()), old)
        book.update(["1cf80156"], {"remove_label": "crop"})
        self.assertEqual(Notebook(self.path, legacy).snapshot()["1cf80156"]["labels"], ["objects"])

    def test_failed_write_preserves_previous_notes(self):
        self.book.update(["task"], {"notes": "original"})
        with patch.object(Path, "replace", side_effect=PermissionError("read only")):
            with self.assertRaises(PermissionError):
                self.book.update(["task"], {"notes": "new"})
        self.assertEqual(self.book.snapshot()["task"]["notes"], "original")
        self.assertEqual(Notebook(self.path, None).snapshot()["task"]["notes"], "original")
        self.assertEqual(list(self.root.glob("*.tmp")), [])

    def test_malformed_store_preserved(self):
        self.path.write_text('{"version": 1, "problems": {"a": {"labels": 3}}}', encoding="utf-8")
        before = self.path.read_bytes()
        with self.assertRaises(ValueError):
            Notebook(self.path, None)
        self.assertEqual(self.path.read_bytes(), before)

    def test_concurrent_edits_merge_fields(self):
        with ThreadPoolExecutor(max_workers=3) as pool:
            futures = [pool.submit(self.book.update, ["task"], value) for value in ({"notes": "reasoning"}, {"add_label": "crop"}, {"starred": True})]
            for future in futures:
                future.result()
        record = Notebook(self.path, None).snapshot()["task"]
        self.assertEqual(record["notes"], "reasoning")
        self.assertEqual(record["labels"], ["crop"])
        self.assertTrue(record["starred"])

    def test_invalid_edits_do_not_change_notebook(self):
        for value in ({"status": "bad"}, {"notes": 23}, {"add_label": " "}, {"starred": "yes"}, {"unexpected": 3}):
            with self.subTest(value=value), self.assertRaises(ValueError):
                self.book.update(["task"], value)
        self.assertEqual(self.book.snapshot(), {})

    def test_layers_persist_with_stable_links_without_replacing_notes(self):
        self.book.update(["a"], {"notes": "Existing solution", "labels": ["crop"], "status": "Reviewed"})
        self.book.update(["a"], {"layers": LAYERS})
        record = Notebook(self.path, None).snapshot()["a"]
        self.assertEqual(record["layers"], LAYERS)
        self.assertEqual(record["notes"], "Existing solution")
        self.assertEqual(record["labels"], ["crop"])
        self.assertEqual(record["status"], "Reviewed")
        renamed = copy.deepcopy(LAYERS)
        renamed[0]["name"] = "Visible cells"
        self.book.update(["a"], {"layers": renamed})
        self.assertEqual(self.book.snapshot()["a"]["layers"][1]["built_from"], ["direct"])
        self.assertEqual(json.loads(self.path.read_text())["version"], 5)

    def test_v1_notebook_loads_without_rewriting_or_losing_user_data(self):
        old = {"version": 1, "problems": {"a": {"notes": "My notes", "labels": ["objects"], "status": "Investigating", "starred": True}}}
        self.path.write_text(json.dumps(old))
        original = self.path.read_bytes()
        book = Notebook(self.path, None)
        self.assertEqual(book.snapshot()["a"]["layers"], [])
        self.assertEqual(self.path.read_bytes(), original)
        book.update(["b"], {"layers": LAYERS})
        record = Notebook(self.path, None).snapshot()["a"]
        self.assertEqual(record["notes"], "My notes")
        self.assertEqual(record["status"], "Uncertain")
        self.assertTrue(record["starred"])

    def test_review_statuses_persist_and_default_to_awaiting_review(self):
        self.book.update(["new"], {"notes": "A note"})
        self.assertEqual(self.book.snapshot()["new"]["status"], "Awaiting Review")
        for status in STATUSES:
            with self.subTest(status=status):
                self.book.update(["new"], {"status": status})
                self.assertEqual(Notebook(self.path, None).snapshot()["new"]["status"], status)
                self.assertEqual(self.book.snapshot()["new"]["notes"], "A note")

    def test_old_review_statuses_migrate_without_rewriting_on_load(self):
        mapping = {"Unreviewed": "Awaiting Review", "Investigating": "Uncertain", "Understood": "Reviewed"}
        self.path.write_text(json.dumps({"version": 5, "problems": {key: {"status": key} for key in mapping}}))
        before = self.path.read_bytes()
        book = Notebook(self.path, None)
        self.assertEqual(self.path.read_bytes(), before)
        self.assertEqual({key: record["status"] for key, record in book.snapshot().items()}, mapping)
        book.update(["Unreviewed"], {"starred": True})
        self.assertEqual({key: record["status"] for key, record in Notebook(self.path, None).snapshot().items()}, mapping)

    def test_invalid_layer_graph_does_not_overwrite_saved_layers(self):
        self.book.update(["a"], {"layers": LAYERS})
        invalid = []
        for dependencies in (["objects"], ["absent"], ["direct"], [2]):
            layers = copy.deepcopy(LAYERS)
            layers[0]["built_from"] = dependencies
            invalid.append(layers)
        duplicate = copy.deepcopy(LAYERS)
        duplicate[1]["id"] = duplicate[0]["id"]
        invalid.extend([duplicate, list(reversed(LAYERS)), "not layers"])
        for layers in invalid:
            with self.subTest(layers=layers), self.assertRaises(ValueError):
                self.book.update(["a"], {"layers": layers})
        self.assertEqual(Notebook(self.path, None).snapshot()["a"]["layers"], LAYERS)

    def test_evidence_rejects_missing_grids_and_invalid_indices(self):
        validate_evidence(LAYERS, TASK)
        for link in (
            {"section": "test", "index": 0, "grid": "output"},
            {"section": "train", "index": 1, "grid": "input"},
            {"section": "train", "index": True, "grid": "input"},
            {"section": "train", "index": -1, "grid": "input"},
        ):
            layers = copy.deepcopy(LAYERS)
            layers[0]["evidence"] = [link]
            with self.subTest(link=link), self.assertRaises(ValueError):
                validate_evidence(layers, TASK)
        layers = copy.deepcopy(LAYERS)
        layers[1]["built_from"] *= 2
        layers[0]["evidence"] *= 2
        self.assertEqual(validate_layers(layers), LAYERS)


class OpenNotebookTests(unittest.TestCase):
    def test_input_output_fields_persist_with_metadata_and_preserve_prior_work(self):
        fields = {"input_background": "Black cells.\nUnchanged elsewhere.", "output_background": "White cells.", "input_objects": "Two red objects.", "output_objects": "One blue object.", "input_object_relationships": "They touch diagonally.", "output_object_relationships": "Centered on the background.", "transformations": "Move inward.", "strategy": "Match the shapes → align."}
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "notes.json"
            old = {"version": 3, "problems": {"a": {"notes": "Original", "layers": LAYERS, "solution": blank_solution()}}}
            path.write_text(json.dumps(old))
            before = path.read_bytes()
            book = Notebook(path, None)
            self.assertEqual(path.read_bytes(), before)
            metadata = {"a": {"problem_id": "a", "problem_sets": ["Training", "Milestone B"], "training_examples": 3, "test_examples": 1, "changes_grid_size": True}}
            book.update(["a"], {"fields": fields}, metadata)
            record = Notebook(path, None).snapshot()["a"]
            self.assertEqual(record["fields"], fields)
            self.assertEqual(record["metadata"], metadata["a"])
            self.assertEqual(record["layers"], LAYERS)
            self.assertEqual(record["notes"], "Original")
            self.assertEqual(record["solution"], blank_solution())
            blank = dict.fromkeys(fields, "")
            book.update(["b"], {"fields": blank})
            self.assertEqual(book.snapshot()["a"]["fields"], fields)
            for invalid in ({}, {**fields, "strategy": 7}, {**fields, "extra": "bad"}, {**fields, "input_objects": "x" * 20001}):
                with self.assertRaises(ValueError):
                    book.update(["a"], {"fields": invalid})
            self.assertEqual(book.snapshot()["a"]["fields"], fields)

    def test_v4_fields_migrate_without_rewriting_saved_file(self):
        fields = {"background": "Black", "objects": "Two red shapes", "object_relationships": "Touching", "transformations": "Move", "strategy": "Align"}
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "notes.json"
            path.write_text(json.dumps({"version": 4, "problems": {"a": {"fields": fields, "notes": "Earlier notes"}}}))
            before = path.read_bytes()
            book = Notebook(path, None)
            migrated = book.snapshot()["a"]["fields"]
            self.assertEqual(path.read_bytes(), before)
            self.assertEqual(set(migrated), set(NOTEBOOK_FIELDS))
            for name in ("background", "objects", "object_relationships"):
                self.assertEqual(migrated["input_" + name], fields[name])
                self.assertEqual(migrated["output_" + name], "")
            self.assertEqual(migrated["transformations"], "Move")
            self.assertEqual(migrated["strategy"], "Align")
            book.update(["a"], {"starred": True})
            self.assertEqual(json.loads(path.read_text())["version"], 5)
            reloaded = Notebook(path, None).snapshot()["a"]
            self.assertEqual(reloaded["fields"], migrated)
            self.assertEqual(reloaded["notes"], "Earlier notes")


class SolutionTests(unittest.TestCase):
    def test_partial_solution_is_explicit_and_independent(self):
        solution = blank_solution()
        self.assertEqual(validate_solution(solution), solution)
        self.assertIsNone(solution["input"]["background"])
        solution["input"]["background"] = "none"
        self.assertIsNone(blank_solution()["input"]["background"])

    def test_typed_steps_round_trip_and_preserve_existing_notes(self):
        solution = blank_solution()
        solution["input"].update(background="fixed_color", background_color="0", units="objects")
        solution["steps"] = [{"id": "move", "operation": "translate", "source": "selection", "application": "per_unit", "condition": None, "parameters": {"row_offset": -2, "column_offset": 0}}]
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "notes.json"
            path.write_text(json.dumps({"version": 2, "problems": {"a": {"notes": "Original reasoning", "layers": LAYERS, "labels": ["crop"]}}}))
            before = path.read_bytes()
            book = Notebook(path, None)
            self.assertEqual(path.read_bytes(), before)
            self.assertNotIn("solution", book.snapshot()["a"])
            book.update(["a"], {"solution": solution})
            record = Notebook(path, None).snapshot()["a"]
            self.assertEqual(record["solution"], solution)
            self.assertEqual(record["notes"], "Original reasoning")
            self.assertEqual(record["layers"], LAYERS)
            self.assertEqual(record["labels"], ["crop"])

    def test_invalid_types_parameters_and_dependencies_are_rejected(self):
        valid = blank_solution()
        valid["steps"] = [{"id": "move", "operation": "translate", "source": "selection", "application": "once", "condition": None, "parameters": {"row_offset": 0, "column_offset": -2}}]
        bad = []
        for value in (True, "2", 1.5, 101):
            item = copy.deepcopy(valid)
            item["steps"][0]["parameters"]["row_offset"] = value
            bad.append(item)
        for key, value in (("source", "previous"), ("operation", "unknown"), ("parameters", {"angle": 90})):
            item = copy.deepcopy(valid)
            item["steps"][0][key] = value
            bad.append(item)
        item = copy.deepcopy(valid)
        item["steps"].append(copy.deepcopy(item["steps"][0]))
        bad.append(item)
        item = copy.deepcopy(valid)
        item["input"]["background_color"] = "0"  # Inactive without fixed_color.
        bad.append(item)
        item = copy.deepcopy(valid)
        item["output"]["size"] = "made_up"
        bad.append(item)
        with tempfile.TemporaryDirectory() as directory:
            book = Notebook(Path(directory) / "notes.json", None)
            book.update(["a"], {"solution": valid})
            for value in bad:
                with self.subTest(value=value), self.assertRaises(ValueError):
                    book.update(["a"], {"solution": value})
                self.assertEqual(book.snapshot()["a"]["solution"], valid)


class CatalogTests(unittest.TestCase):
    def test_validation_and_missing_test_output(self):
        self.assertEqual(validate_task(TASK), TASK)
        for grid in ([], [[]], [[1], [1, 2]], [[True]], [[10]], [["2"]]):
            with self.subTest(grid=grid), self.assertRaises(ValueError):
                grid_size(grid)

    def test_duplicate_sources_share_problem_and_imports_persist(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "dataset"
            for folder in (source / "train", source / "milestone"):
                folder.mkdir(parents=True)
                (folder / "1cf80156.json").write_text(json.dumps(TASK))
            catalog = Catalog(source, root / "imports")
            self.assertEqual(len(catalog.index()), 1)
            self.assertEqual(len(catalog.index()[0]["sets"]), 2)
            self.assertEqual(catalog.index()[0]["shape"], "Changes size")
            catalog.import_task("folder/newtask.json", TASK)
            self.assertIn("newtask", Catalog(source, root / "imports").problems)
            changed = copy.deepcopy(TASK)
            changed["test"][0]["input"] = [[3]]
            with self.assertRaises(ValueError):
                catalog.import_task("newtask.json", changed)
            self.assertEqual(load_task(root / "imports" / "newtask.json"), TASK)

    @unittest.skipUnless(
        (Path(__file__).resolve().parent.parent / "ARC-AGI-master" / "ARC-AGI-master" / "data" / "training").is_dir(),
        "Optional bundled ARC datasets are not installed.",
    )
    def test_bundled_datasets_load_without_errors(self):
        with tempfile.TemporaryDirectory() as directory:
            catalog = Catalog(imports=Path(directory))
            self.assertEqual(catalog.warnings, [])
            self.assertEqual(len(catalog.problems), 800)
            self.assertIn("Milestones / B", catalog.problems["1cf80156"]["sets"])


class ServerTests(unittest.TestCase):
    def test_api_auth_persistence_and_missing_output(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "a.json").write_text(json.dumps(TASK))
            catalog = Catalog(root, root / "imports")
            notebook = Notebook(root / "notes.json", None)
            server = create_server(catalog, notebook)
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            url = f"http://127.0.0.1:{server.server_port}"
            try:
                html = urlopen(url).read().decode()
                token = re.search(r'name="workspace-token" content="([^"]+)"', html)[1]
                with self.assertRaises(HTTPError) as denied:
                    urlopen(url + "/api/library")
                self.assertEqual(denied.exception.code, 403)
                denied.exception.close()
                def request(path, data=None):
                    req = Request(url + path, data=json.dumps(data).encode() if data is not None else None, headers={"X-Workspace-Token": token})
                    with urlopen(req) as response:
                        return json.load(response)
                self.assertEqual(request("/api/problem?id=a"), TASK)
                self.assertEqual(request("/api/library")["notebook_fields"], list(NOTEBOOK_FIELDS))
                self.assertEqual(request("/api/library")["review_statuses"], list(STATUSES))
                for status in STATUSES:
                    changed = request("/api/annotate", {"ids": ["a"], "patch": {"status": status}})
                    self.assertEqual(changed["a"]["status"], status)
                    self.assertEqual(Notebook(notebook.path, None).snapshot()["a"]["status"], status)
                fields = {key: key + " text" for key in NOTEBOOK_FIELDS}
                request("/api/annotate", {"ids": ["a"], "patch": {"fields": fields}})
                persisted = Notebook(notebook.path, None).snapshot()["a"]
                self.assertEqual(persisted["fields"], fields)
                self.assertEqual(persisted["metadata"], catalog.metadata("a"))
                self.assertEqual(persisted["metadata"]["training_examples"], 1)
                self.assertEqual(persisted["metadata"]["problem_id"], "a")
                self.assertEqual(request("/api/library")["problems"][0]["metadata"], persisted["metadata"])
                with self.assertRaises(HTTPError) as forged:
                    request("/api/annotate", {"ids": ["a"], "patch": {"metadata": {"problem_id": "other"}}})
                self.assertEqual(forged.exception.code, 400)
                forged.exception.close()
                request("/api/annotate", {"ids": ["a"], "patch": {"solution": blank_solution()}})
                self.assertEqual(Notebook(notebook.path, None).snapshot()["a"]["solution"], blank_solution())
                request("/api/annotate", {"ids": ["a"], "patch": {"notes": "A hypothesis", "add_label": "rotation"}})
                self.assertEqual(request("/api/library")["annotations"]["a"]["labels"], ["rotation"])
                self.assertEqual(Notebook(notebook.path, None).snapshot()["a"]["notes"], "A hypothesis")
                request("/api/annotate", {"ids": ["a"], "patch": {"layers": LAYERS}})
                self.assertEqual(request("/api/library")["annotations"]["a"]["layers"], LAYERS)
                missing_output = copy.deepcopy(LAYERS)
                missing_output[0]["evidence"] = [{"section": "test", "index": 0, "grid": "output"}]
                with self.assertRaises(HTTPError) as bad_link:
                    request("/api/annotate", {"ids": ["a"], "patch": {"layers": missing_output}})
                self.assertEqual(bad_link.exception.code, 400)
                bad_link.exception.close()
                self.assertEqual(notebook.snapshot()["a"]["layers"], LAYERS)
                self.assertEqual(load_task(root / "a.json"), TASK)
                with self.assertRaises(HTTPError) as invalid:
                    request("/api/annotate", {"ids": ["absent"], "patch": {"notes": "bad"}})
                invalid.exception.close()
            finally:
                server.shutdown()
                server.server_close()
                thread.join()


if __name__ == "__main__":
    unittest.main()
