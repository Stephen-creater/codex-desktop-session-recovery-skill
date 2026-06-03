# Codex Desktop Session Recovery Skill

This repository packages a reproducible recovery workflow for a specific Codex Desktop failure class:

- local chats still exist on disk
- `~/.codex/state_5.sqlite` still contains the threads
- `~/.codex/sessions/...jsonl` still exists
- the Desktop app sidebar or project view hides the chats anyway

It does not patch the Codex app bundle. It focuses on the local state that is safe to audit and, when needed, repair:

- `state_5.sqlite`
- `session_index.jsonl`
- `.codex-global-state.json`
- saved workspace roots and project ordering
- `projectless-thread-ids`
- `thread-workspace-root-hints`

That last mapping matters: without it, a project can reappear in the sidebar while its internal chat list still shows `No chats` / `暂无对话`.

## What This Repo Delivers

- A reusable local skill
- A single Python recovery tool with `audit`, `repair`, `repair-session-index`, `heal`, `verify`, and `report`
- A root-cause model for three common failure modes
- A conservative repair flow with dry-run by default and automatic backup on write

## Layout

- [skill/codex-desktop-session-recovery/SKILL.md](skill/codex-desktop-session-recovery/SKILL.md)
- [skill/codex-desktop-session-recovery/scripts/codex_session_recovery.py](skill/codex-desktop-session-recovery/scripts/codex_session_recovery.py)
- [docs/root-cause.md](docs/root-cause.md)
- [docs/decision-table.md](docs/decision-table.md)
- [docs/community-signals.md](docs/community-signals.md)
- [docs/article-draft.md](docs/article-draft.md)

## Quick Start

Run a read-only audit against the default Codex home:

```bash
python3 skill/codex-desktop-session-recovery/scripts/codex_session_recovery.py audit
```

Preview both repair steps without writing:

```bash
python3 skill/codex-desktop-session-recovery/scripts/codex_session_recovery.py repair
```

Apply the repair with a minimal backup:

```bash
python3 skill/codex-desktop-session-recovery/scripts/codex_session_recovery.py repair --apply
```

Repair just the local session index:

```bash
python3 skill/codex-desktop-session-recovery/scripts/codex_session_recovery.py repair-session-index --apply
```

Force one old project back into the recent window:

```bash
python3 skill/codex-desktop-session-recovery/scripts/codex_session_recovery.py surface-project --cwd "/absolute/project/path" --apply
```

Verify the result against the backup that was created:

```bash
python3 skill/codex-desktop-session-recovery/scripts/codex_session_recovery.py verify --backup-dir ~/.codex/backups/session-recovery/<timestamp>
```

Generate a Markdown incident report:

```bash
python3 skill/codex-desktop-session-recovery/scripts/codex_session_recovery.py report
```

Run an idempotent self-heal preview:

```bash
python3 skill/codex-desktop-session-recovery/scripts/codex_session_recovery.py heal
```

## Repair Philosophy

- Dry-run first
- Never delete raw sessions
- Back up only the files being changed
- Prefer state reclassification over destructive rewrites
- Treat recent-window hiding and project-mapping breakage as separate bugs

## Self-Healing Watchdog

This repo also supports an optional macOS `launchd` watchdog that runs `heal --apply` at login, on a schedule, and whenever `.codex-global-state.json` changes.

Preview the plist:

```bash
python3 skill/codex-desktop-session-recovery/scripts/codex_session_recovery.py watchdog-print
```

Install the watchdog:

```bash
python3 skill/codex-desktop-session-recovery/scripts/codex_session_recovery.py watchdog-install
```

Remove it:

```bash
python3 skill/codex-desktop-session-recovery/scripts/codex_session_recovery.py watchdog-uninstall
```

## Local Installation As A Skill

Create a symlink into `~/.codex/skills`:

```bash
mkdir -p ~/.codex/skills
ln -sfn \
  "$(pwd)"/skill/codex-desktop-session-recovery \
  ~/.codex/skills/codex-desktop-session-recovery
```

## External Evidence

- [Codex app features](https://developers.openai.com/codex/app/features)
- [Codex memories](https://developers.openai.com/codex/memories)
- [Codex skills](https://developers.openai.com/codex/skills)
- [Issue #23979: local project conversation history missing after update](https://github.com/openai/codex/issues/23979)
- [Issue #20833: project sidebar hides older workspace conversations](https://github.com/openai/codex/issues/20833)
- [Issue #22796: project sidebar shows No chats while local sessions still exist](https://github.com/openai/codex/issues/22796)
- [Issue #21128: silently hides project conversations outside the global recent-50 window](https://github.com/openai/codex/issues/21128)
- [Issue #24364: WSL cwd/path migration mismatch](https://github.com/openai/codex/issues/24364)
