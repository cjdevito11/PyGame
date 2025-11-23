# Debugging and diagnostics

Keep these helpers nearby while experimenting with new content or mechanics.

## Logging

- Set `LOG_LEVEL=DEBUG` in your environment to see detailed, structured logs from every system.
- Logs include per-system names (for example `systems.combat`) and key/value payloads so you can skim for the fields you care about.

Example:

```bash
LOG_LEVEL=DEBUG python -m ui.game
```

## Validation hints

Validation errors now point at the offending field path (for example `characters.Shade.class_name`). Use that breadcrumb to jump straight to the YAML/JSON field that needs attention. Running `python -m unittest tests.test_logging_and_validation` will exercise the registry loaders and surface any data quality issues.
