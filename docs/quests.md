# Quest rewards and training data

Quest rewards are now defined alongside other content in the `data/` folder.
The runtime loader looks for `quests.yaml` or `quests.json` and registers each
entry with the `QuestSystem` during `GameContext` creation.

## Data format

Each quest entry supports the following fields:

- `identifier`, `description`, `trigger_event`, and `owner`: standard metadata
  passed to `QuestSystem.register_quest`.
- `condition_field` and `condition_value`: optional helpers that build a simple
  equality check against the triggering event payload (e.g., `defender ==
  "Shade"`).
- `target_monsters`: per-monster kill targets to drive progress updates.
- `reward_gold`: integer reward that flows through the `economy.reward`
  handler.
- `reward_items`: list of item identifiers to grant through
  `CombatSystem.add_item`. A legacy `reward_item` field also exists for single
  items and is merged into `reward_items` when present.
- `reward_attributes`: stat bonuses keyed by `strength`, `agility`, or
  `mastery` that are applied directly to the owning `Combatant`.
- `reward_skills`: map of skill names to ranks that increment the player's
  known skill levels.
- `loot_queue`: optional ordered list of interim loot handed out as objectives
  complete.

See `data/quests.json` for a concrete example that rewards gear and
strength/agility/skill bumps when Shade is defeated.

## Starter stats and skills

Player-facing stats live on the `Combatant` object. They are initialized from
`data/characters.json` using two new fields:

- `stats`: dictionary containing `strength`, `agility`, and `mastery` seed
  values.
- `skills`: dictionary mapping skill names to starting ranks.

These values flow into combat math (baseline attack power, defensive resilience)
and display in both the HUD and inventory UI. Quest rewards that grant
attributes or skills update these same fields so subsequent attacks immediately
reflect the new bonuses.

## Authoring tips

1. Add new quest entries to `data/quests.yaml` or `data/quests.json`; the loader
   prefers YAML if both exist.
2. Reference existing items (in `data/items.json`) for `reward_items` or add new
   items first.
3. Keep stat increments small (e.g., 1–2 points) to avoid overpowering early
   fights.
4. Use skill names that surface clearly to players—the HUD renders them with
   title-cased words and ranks.
5. When testing, watch for `inventory.item_added` and `quest.completed` events
   in the logs to verify that your payload includes the rewards you expect.
