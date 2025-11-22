# Contributor quickstart

This guide keeps content additions simple and repeatable. Each example mirrors the data-driven flow used by the CLI and the automated exercises.

## How to add a new class, appearance, or item

1. Pick a clear identifier and write it down **before** editing files. The registries reject duplicates.
2. Update the matching file under `data/`:
   - `data/appearances.yaml` for map symbols and colors
   - `data/classes.yaml` for stats
   - `data/items.json` for equipment
3. Run the CLI to check your edits and see the new entry.

Example (appearance) with inline comments:

```yaml
# data/appearances.yaml
- name: ember_sprite          # short, lowercase identifier
  description: Flickers near old campfires.
  symbol: "e"                  # single character used on the map
  color: orange                # any readable color name
```

Quick CLI transcript you can copy:

```bash
python -m ui.cli data list appearances
python -m ui.cli data show appearances ember_sprite
python -m ui.cli data validate
```

Item example (kept tiny for readability):

```json
{
  "name": "camp_mug",             // snake_case names stay consistent with files
  "description": "Keeps tea warm.",
  "slot": "offhand",
  "power": 0
}
```

## Exercises with ready-made tests

The `tests/test_content_exercises.py` suite walks through creating new content from data files. Run it after each experiment to confirm you wired things correctly:

```bash
python -m unittest tests.test_content_exercises
```

What the exercises cover:

- Loading a fresh appearance definition from YAML and instantiating it via the registry
- Adding a new player class with bounded stats
- Driving a branching quest outcome from a small YAML file and an event payload

If you want to follow along manually, reuse the commented fixture files under `tests/fixtures/`—they stay short on purpose to highlight the required fields.

## Coding standards and naming conventions

- Use **snake_case** for file names and identifiers inside JSON/YAML.
- Keep descriptions friendly and complete sentences; errors echo them back to the CLI.
- One responsibility per function; avoid try/except wrappers around imports to surface missing dependencies immediately.
- Prefer small, commented examples in docs and tests. If a block feels dense, split it and add a clarifying comment.
- Stick to standard library features in tests unless a dependency is already in `requirements.txt`.

## Checklist for PRs and local changes

1. Run data validation: `python -m ui.cli data validate`
2. Run unit tests (fast): `python -m unittest`
3. Format/clarify docs: keep examples commented and identifiers in snake_case
4. Describe the change clearly in the commit message and PR summary

Working through the checklist keeps contributions beginner-friendly and avoids schema surprises for reviewers.
