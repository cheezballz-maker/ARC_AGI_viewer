# ARC Fieldnotes

A local workspace for studying ARC problems, recording a proposed solution, and
tracking review status. Each problem ID has one notebook shared by its dataset
copies. Training/test pairs are demonstrations belonging to that problem.

## Launch

From the repository root:

```powershell
python Viewer/view_file_types.py
```

The launcher opens the viewer in your default browser. Keep the
Python process running while using it; Ctrl+C stops it. Python 3.10+ is required;
there are no third-party dependencies, remote assets, or network services.
The server listens only on `127.0.0.1` on an automatically selected port.

Optional arguments:

```powershell
python Viewer/view_file_types.py path/to/problem.json
python Viewer/view_file_types.py path/to/dataset
python Viewer/view_file_types.py --no-browser --port 8765
```

This viewer repository does not include datasets or personal notebooks. Supply
an ARC task JSON or dataset folder as the optional launch argument, or use
Open JSON / Open folder to import problems. With no dataset installed, the first
launch shows an empty library.

When installed in the larger ARC workspace, the library also discovers the
training/evaluation datasets under `ARC-AGI-master/ARC-AGI-master/data/` and sets
under `ArcAgi-StarterCode_v1.4.0.1/Milestones/` alongside `Viewer/`.
Identical IDs appear once, with all their set memberships.
Open JSON and Open folder import copies of additional problems for future use.
An import with a conflicting existing ID is rejected; rename it to give it a
distinct notebook. Invalid files are reported without preventing valid imports.

## Problem notebook

Each problem has eight open-ended text fields: separate Input and Output versions
of Background, Objects, and Object relationships, plus Transformations and
Strategy. All accept multiline text (up to
20,000 characters each). There are no inferred rules or predefined choices.
Input and Output appear side by side under each shared field heading.

After updating the viewer code, restart its Python process and refresh the page.
The browser checks that the server supports the notebook fields and statuses before saving.
If a restart is needed, drafts stay in the browser and can be exported first.

Earlier notebooks load their Background, Objects, and Object relationships notes
into the corresponding Input fields; Output fields start empty. Loading preserves
the original file, and the next successful save writes the updated schema.

Edits autosave after a short pause, on leaving a field, and on switching problems.
Save notebook or Ctrl+S also saves. A failed save retains the draft and displays
an error. Export problem JSON downloads the current problem; Export all
notebooks downloads all recorded annotations. Exports include pending drafts.

The server writes `Viewer/problem_annotations.json` atomically. It uses the
problem ID as the key, shared across duplicate dataset copies. Schema version 5
contains records of this form (other retained annotation keys are omitted here):

```json
{
  "version": 5,
  "problems": {
    "1cf80156": {
      "metadata": {
        "problem_id": "1cf80156",
        "problem_sets": ["ARC · Training", "Milestones / B"],
        "training_examples": 3,
        "test_examples": 1,
        "changes_grid_size": true
      },
      "fields": {
        "input_background": "",
        "output_background": "",
        "input_objects": "",
        "output_objects": "",
        "input_object_relationships": "",
        "output_object_relationships": "",
        "transformations": "",
        "strategy": ""
      },
      "updated": "2026-10-01T00:00:00+00:00"
    }
  }
}
```

Metadata comes from the loaded catalog on save, not editable notebook text.
`updated` records the last successful save in UTC. Exports use the current
catalog metadata for available problems. The example timestamp above is
illustrative. Blank fields are empty strings. No LLM service is called.

Versions 1–4 remain readable without rewriting on load. Older notes, layers,
structured solutions, and labels remain in saved records and exports.
A saved edit upgrades the file to version 5.

Assign a problem's status using Review status at the top of its Problem notebook.
Changes save immediately. Choose Reviewed, Awaiting Review, or Uncertain;
new problems default to Awaiting Review. The left panel's Review status rows
filter the library. Older statuses migrate as follows: Unreviewed → Awaiting
Review, Investigating → Uncertain, and Understood → Reviewed.

## Browsing and layout

Click a review status or problem set to filter the library. Each row shows its
count across all loaded problems; counts update after status changes and imports.
Problems included in multiple sets count once in each set, while All problem sets
counts unique problems. Clear filters resets the search and all filters.
More filters contains bookmarks, notes, and dimension changes. Search includes
the eight notebook fields, IDs, and retained notes/layers. Has notes includes any
filled notebook field. Label controls and bulk selection have been removed;
earlier labels are preserved in saved records and exports.

Press `/` to search and Alt+Left/Right to navigate the filtered results.
Grids always fit the available card space and resize automatically with the panels.
On narrow windows, Notebook opens the notes panel. Drag either panel divider to
resize it; the notebook drawer also resizes from its left edge. Focus a divider
and use Left/Right (Shift for larger steps), Home/End for limits, or Enter to
reset; double-click also resets. Widths are remembered by the browser for the
viewer address and adapt to available space.

## Local data

- `problem_annotations.json`: notebook fields, metadata, and retained annotations.
- `imports/`: imported problem copies.
- `example_labels.json`: older sample labels, merged by problem ID on first
  launch if no notebook file exists. The original file is retained.

Personal files are excluded from Git; original ARC files are not edited. To
restore a full backup, stop the viewer and copy an Export all notebooks file to
`Viewer/problem_annotations.json`. A single-problem export is only a partial
backup. Run one viewer process per notebook file at a time.

## Validation

```powershell
python -m unittest discover -s Viewer -v
node --check Viewer/web/app.js
node --test Viewer/test_viewer_web.cjs
```

Tests cover persistence, migration, concurrent request edits, failed writes,
duplicate problem sets, imports, data validation, and the local HTTP API.
The bundled-dataset integration test is skipped when the optional ARC datasets
are absent. Node.js is needed only for JavaScript validation and frontend tests.
