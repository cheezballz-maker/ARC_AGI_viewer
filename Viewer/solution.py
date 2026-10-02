"""Typed solution descriptions shared by the notebook form and JSON validator."""

from __future__ import annotations

import copy
import re


def choice(key, label, options):
    return {"key": key, "label": label, "type": "choice", "options": [{"value": value, "label": title} for value, title in options]}


def number(key, label, minimum, maximum):
    return {"key": key, "label": label, "type": "integer", "min": minimum, "max": maximum}


def text(key, label):
    return {"key": key, "label": label, "type": "text", "max_length": 5000}


def when(field, key, value):
    return field | {"when": {"key": key, "value": value}}


COLOR = [(str(value), str(value)) for value in range(10)]
SCHEMA = {
    "version": 1,
    "sections": [
        {"key": "input", "label": "Input interpretation", "fields": [
            choice("background", "Background", [("fixed_color", "Fixed color"), ("most_frequent", "Most frequent color"), ("none", "No background"), ("custom", "Custom rule")]),
            when(choice("background_color", "Background color", COLOR), "background", "fixed_color"),
            when(text("background_rule", "Background rule"), "background", "custom"),
            choice("units", "Working units", [("cells", "Cells"), ("objects", "Objects"), ("regions", "Regions"), ("rows_columns", "Rows / columns"), ("repeating_tiles", "Repeating tiles"), ("whole_grid", "Whole grid"), ("custom", "Custom units")]),
            when(text("unit_rule", "Unit definition"), "units", "custom"),
            choice("grouping", "Grouping", [("same_color", "Same-color components"), ("non_background", "Non-background components"), ("enclosed_regions", "Enclosed regions"), ("repeating_pattern", "Repeating pattern"), ("none", "No grouping"), ("custom", "Custom grouping")]),
            choice("connectivity", "Connectivity", [("4", "4-way (edges)"), ("8", "8-way (edges + corners)"), ("not_applicable", "Not applicable")]),
            when(text("grouping_rule", "Grouping rule"), "grouping", "custom"),
        ]},
        {"key": "selection", "label": "Selection", "fields": [
            choice("scope", "Select from", [("whole_grid", "Whole grid"), ("foreground", "Foreground cells"), ("background", "Background cells"), ("units", "Interpreted units")]),
            choice("criterion", "Selection criterion", [("all", "All"), ("largest", "Largest area"), ("smallest", "Smallest area"), ("color", "Color"), ("unique_shape", "Unique shape"), ("unique_color", "Unique color"), ("touches_border", "Touches border"), ("enclosed", "Enclosed"), ("custom", "Custom predicate")]),
            when(choice("color", "Selected color", COLOR), "criterion", "color"),
            when(text("predicate", "Selection predicate"), "criterion", "custom"),
            choice("ties", "If multiple matches", [("all", "Select all matches"), ("topmost_leftmost", "Topmost, then leftmost"), ("none", "Expect exactly one"), ("custom", "Custom tie-break")]),
            when(text("tie_rule", "Tie-break rule"), "ties", "custom"),
        ]},
        {"key": "output", "label": "Output construction", "fields": [
            choice("size", "Grid dimensions", [("same_as_input", "Same as input"), ("selection_bounds", "Selection bounding box"), ("result", "Final step dimensions"), ("fixed", "Fixed dimensions"), ("custom", "Custom size rule")]),
            when(number("rows", "Rows", 1, 100), "size", "fixed"),
            when(number("columns", "Columns", 1, 100), "size", "fixed"),
            when(text("size_rule", "Size rule"), "size", "custom"),
            choice("base", "Starting canvas", [("input", "Copy input"), ("blank", "Blank canvas"), ("result", "Final step result")]),
            when(choice("fill_color", "Canvas color", COLOR), "base", "blank"),
            choice("placement", "Result placement", [("original", "Original coordinates"), ("top_left", "Top left"), ("center", "Centered"), ("result", "As produced by final step"), ("custom", "Custom placement")]),
            when(text("placement_rule", "Placement rule"), "placement", "custom"),
            choice("overlap", "Overlapping cells", [("overwrite", "Later result overwrites"), ("preserve", "Keep existing foreground"), ("none", "No overlap expected"), ("custom", "Custom overlap rule")]),
            when(text("overlap_rule", "Overlap rule"), "overlap", "custom"),
        ]},
    ],
    "step_fields": [
        choice("source", "Apply to", [("selection", "Selected cells / units"), ("input", "Whole input"), ("previous", "Previous step result")]),
        choice("application", "Application", [("once", "Once to the whole selection"), ("per_unit", "Individually to each unit")]),
        text("condition", "Condition (optional)"),
    ],
    "operations": [
        {"key": "copy", "label": "Copy", "fields": []},
        {"key": "crop", "label": "Crop", "fields": [
            choice("bounds", "Crop bounds", [("selection", "Selection bounding box"), ("foreground", "Foreground bounding box"), ("custom", "Custom bounds")]),
            when(text("bounds_rule", "Bounds rule"), "bounds", "custom"),
            choice("interior", "Inside the bounds", [("preserve", "Preserve every cell"), ("selected_only", "Keep selected cells only")]),
        ]},
        {"key": "rotate", "label": "Rotate", "fields": [choice("degrees", "Clockwise rotation", [("90", "90°"), ("180", "180°"), ("270", "270°")])]},
        {"key": "reflect", "label": "Reflect", "fields": [choice("axis", "Reflection axis", [("vertical", "Vertical axis (left ↔ right)"), ("horizontal", "Horizontal axis (top ↔ bottom)"), ("main_diagonal", "Main diagonal"), ("anti_diagonal", "Anti-diagonal")])]},
        {"key": "translate", "label": "Move", "fields": [number("row_offset", "Row offset (+ down)", -100, 100), number("column_offset", "Column offset (+ right)", -100, 100)]},
        {"key": "recolor", "label": "Recolor", "fields": [choice("from_color", "From color", COLOR), choice("to_color", "To color", COLOR)]},
        {"key": "scale", "label": "Scale", "fields": [number("row_factor", "Row scale factor", 1, 100), number("column_factor", "Column scale factor", 1, 100)]},
        {"key": "repeat", "label": "Repeat", "fields": [number("row_copies", "Copies vertically", 1, 100), number("column_copies", "Copies horizontally", 1, 100)]},
        {"key": "fill", "label": "Fill", "fields": [choice("color", "Fill color", COLOR), choice("region", "Fill region", [("selected", "Selected cells"), ("bounds", "Bounding rectangle"), ("holes", "Enclosed holes")])]},
        {"key": "custom", "label": "Custom transformation", "fields": [text("rule", "Transformation rule")]},
    ],
}


def blank_fields(fields):
    return {field["key"]: None for field in fields}


def blank_solution():
    return {"version": 1, **{section["key"]: blank_fields(section["fields"]) for section in SCHEMA["sections"]}, "steps": []}


def validate_fields(value, fields):
    if not isinstance(value, dict) or set(value) != {field["key"] for field in fields}:
        raise ValueError("Solution fields do not match the schema.")
    result = copy.deepcopy(value)
    for field in fields:
        key = field["key"]
        item = value[key]
        condition = field.get("when")
        if condition and value.get(condition["key"]) != condition["value"]:
            if item is not None:
                raise ValueError(f"Inactive solution field '{key}' must be unset.")
            continue
        if item is None:
            continue  # Partial specifications are valid; unset is explicit.
        kind = field["type"]
        if kind == "choice" and item not in [option["value"] for option in field["options"]]:
            raise ValueError(f"Invalid choice for '{key}'.")
        if kind == "integer" and (type(item) is not int or not field["min"] <= item <= field["max"]):
            raise ValueError(f"'{key}' must be an integer between {field['min']} and {field['max']}.")
        if kind == "text" and (not isinstance(item, str) or len(item) > field["max_length"]):
            raise ValueError(f"Invalid text for '{key}'.")
    return result


def validate_solution(value):
    if not isinstance(value, dict) or set(value) != set(blank_solution()) or type(value.get("version")) is not int or value["version"] != 1:
        raise ValueError("Unsupported solution specification.")
    result = blank_solution()
    for section in SCHEMA["sections"]:
        result[section["key"]] = validate_fields(value[section["key"]], section["fields"])
    steps = value["steps"]
    if not isinstance(steps, list) or len(steps) > 50:
        raise ValueError("Provide at most 50 transformation steps.")
    seen = set()
    operations = {operation["key"]: operation for operation in SCHEMA["operations"]}
    for index, step in enumerate(steps):
        if not isinstance(step, dict) or set(step) != {"id", "operation", "parameters", *blank_fields(SCHEMA["step_fields"])}:
            raise ValueError("Invalid transformation step fields.")
        identifier = step["id"]
        if not isinstance(identifier, str) or not re.fullmatch(r"[A-Za-z0-9_-]{1,80}", identifier) or identifier in seen:
            raise ValueError("Transformation step IDs must be unique.")
        seen.add(identifier)
        operation = step["operation"]
        if operation is not None and (not isinstance(operation, str) or operation not in operations):
            raise ValueError("Unknown transformation operation.")
        fields = validate_fields({field["key"]: step[field["key"]] for field in SCHEMA["step_fields"]}, SCHEMA["step_fields"])
        if index == 0 and fields["source"] == "previous":
            raise ValueError("The first step cannot use a previous step result.")
        params = validate_fields(step["parameters"], operations[operation]["fields"] if operation else [])
        result["steps"].append({"id": identifier, "operation": operation, **fields, "parameters": params})
    return result
