# Root Cause Model

This repo treats "my Codex chats disappeared" as a visibility problem first, not a deletion problem.

## Failure Mode 1: Recent Window Hiding

The app-server protocol exposes `thread/list` with cursor and limit controls, which implies pagination. The local behavior on this machine is consistent with a limited recent preload:

- active unarchived threads: `238`
- top recent window inspected locally: `50`
- distinct `cwd` values inside that top 50: `13`
- one hot project alone occupied `35` of those `50`

That means older projects can become invisible in the sidebar even when all underlying thread data still exists.

## Failure Mode 2: Projectless Misclassification

The global state file can misclassify real project threads as `projectless`.

On this machine:

- `projectless-thread-ids`: `71`
- `thread-workspace-root-hints`: `71`
- all `71` hints point to the same broad ancestor path under `~/Documents/Codex`
- `69` of those `71` threads actually have external project `cwd` values, so they are not true projectless threads

This is a local state classification bug, not data loss.

## Failure Mode 3: Path / Root Identity Drift

Desktop project history is keyed by `cwd`. The app-server protocol defines the `thread/list` `cwd` filter as an exact match filter, not a fuzzy ancestor match. That means small path identity problems can hide history:

- wrong exact root
- root stored as a broad ancestor
- path migration after updates
- WSL/macOS/OneDrive style path drift

## What The Repair Changes

The repair is intentionally conservative:

1. Reclassify clearly non-projectless threads out of `projectless-thread-ids`
2. Remove stale `thread-workspace-root-hints` for those reclassified threads
3. Rebuild saved workspace roots and project order from exact active thread `cwd` values
4. Leave the underlying session JSONL files and state DB rows untouched

## What The Repair Does Not Claim

- It does not claim to fix every Codex Desktop rendering bug.
- It does not claim the recent window bug is fully solved in the app UI.
- It does not modify the app bundle.
- It does not rewrite your session content.
