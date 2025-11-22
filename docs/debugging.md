# Debugging and diagnostics

Keep these helpers nearby while experimenting with new content or mechanics.

## Logging

- Set `LOG_LEVEL=DEBUG` in your environment to see detailed, structured logs from every system.
- Logs include per-system names (for example `systems.combat`) and key/value payloads so you can skim for the fields you care about.

Example:

```bash
LOG_LEVEL=DEBUG python -m ui.cli validate
```

## CLI debug commands

The CLI exposes a `/debug` group for safe experimentation:

- `python -m ui.cli data debug inspect Aria` — show a character's stats without mutating the world.
- `python -m ui.cli data debug simulate Aria Shade --weapon bronze_sword` — preview the damage and remaining HP for a fight.
- `python -m ui.cli data debug spawn Aria lantern` — add an item to a character's backpack for quick testing.

## Validation hints

Validation errors now point at the offending field path (for example `characters.Shade.class_name`). Use that breadcrumb to jump straight to the YAML/JSON field that needs attention.
