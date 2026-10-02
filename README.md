# ARC AGI Viewer

A local, browser-based viewer for ARC problems with side-by-side input/output
notebooks, autosaving, review statuses, and a counted problem library.

Requires Python 3.10 or newer. No third-party Python packages are required.

```powershell
python Viewer/view_file_types.py
```

Open JSON or Open folder to add ARC problems, or launch with a dataset folder:

```powershell
python Viewer/view_file_types.py path/to/dataset
```

Grids always fit the available display space. Notebooks and imported problems
are stored locally and excluded from Git. This repository contains the viewer,
its tests, and documentation; datasets and personal notes are not included.

See [the viewer guide](Viewer/README.md) for notebook fields, review statuses,
exports, optional datasets, keyboard shortcuts, and validation commands.
