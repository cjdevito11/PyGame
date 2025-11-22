# PyGame

A terminal-friendly demo that shows how to wire data-driven game content using simple registries and schema validation.

## Layout

- `core/`: shared helpers like validation and generic registries.
- `world/`: runtime entity objects and schemas.
- `systems/`: wiring and configuration for registries.
- `ui/`: command-line entry point.
- `persistence/`: YAML/JSON loading utilities.
- `data/`: sample content files you can edit without touching code.
- `tests/`: unit tests covering registries, validation, and dynamic loading.

## Getting started

Install dependencies and try the new real-time Pygame prototype (plus the legacy CLI tools):

```bash
python -m pip install -r requirements.txt

# Real-time prototype (WASD/arrow keys to move, Space to attack)
python -m ui.game

# CLI helpers remain for data inspection and validation
python -m ui.cli list appearances
python -m ui.cli show classes adventurer
python -m ui.cli validate
```

To add new content, drop another entry into the matching file in `data/`. The schemas keep you honest and will show friendly messages if something is missing.

## Contributing

Working inside this repository does not require adding new collaborators. A typical flow for proposing changes is:

1. Make your edits and run the automated checks: `python -m unittest`.
2. Commit locally with a clear message that describes the change.
3. Use the provided PR helper command (exposed to the agent as `make_pr`) to open a pull request. If the command returns a transient `500` error, rerun it after a short pause—the backend occasionally hiccups even when your branch is fine.

For a guided walkthrough of adding new data-driven content, coding standards, and exercises with tests, see `docs/contributing.md`.

### If PR creation keeps failing

In rare cases the PR helper can return repeated `500` responses even when your branch is healthy. A quick checklist before retrying:

- Confirm your working tree is clean: `git status -sb` should show no pending changes.
- Make sure the latest commit exists: `git log -1 --stat` should display your work.
- Re-run the helper once more (do not spam requests)—the service can recover after a short wait.
- If the error persists, capture the response and try again later; no collaborator access is required for the helper to succeed.
