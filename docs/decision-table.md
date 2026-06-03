# Decision Table

## Use Local Repair

Use the local repair flow when all of these are true:

- threads still exist in `state_5.sqlite`
- rollout JSONL files still exist
- the app sidebar or project view hides them
- the problem is local state visibility, not actual database corruption

## Escalate To Official Bug Report

Escalate when any of these are true:

- `state_5.sqlite` rows are missing
- rollout JSONL files are gone
- the app bundle update changed migration checksums and the state DB no longer initializes
- the GUI still hides exact-`cwd` threads even after projectless reclassification and root rebuild

## Safe Write Order

1. `audit`
2. `repair --apply`
3. restart Codex Desktop
4. `verify --backup-dir ...`
5. if still broken, collect `report` output and open/update a GitHub issue

If only `session_index.jsonl` is stale or incomplete, run `repair-session-index --apply`.

If a specific old project is still hidden only because it sits outside the recent window, run `surface-project --cwd <project_path> --apply`.

## If The Bug Recurs After Updates

Use the built-in `heal` mode or install the optional launchd watchdog.

- `heal` writes only when the local state is broken again
- it does not touch session content
- it rewrites only `.codex-global-state.json`
- the watchdog also reacts when `.codex-global-state.json` changes, so it can undo live regressions from the running desktop app

## Default Safety Rules

- never edit `state_5.sqlite` directly in v1
- back up `.codex-global-state.json` before any write
- preserve existing root ordering where possible
- append discovered roots by recency instead of fully re-sorting everything
