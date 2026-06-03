---
name: codex-desktop-session-recovery
description: Use when Codex Desktop hides old project chats, shows No chats for a project, or seems to lose session history even though local files under ~/.codex still exist. Audits state_5.sqlite, session_index.jsonl, and .codex-global-state.json; distinguishes recent-window hiding from projectless/root-mapping breakage; previews and applies conservative local repairs with backup and verification.
---

# Codex Desktop Session Recovery

Use this skill when the user reports that Codex Desktop no longer shows old chats for a project, or that sidebar history disappeared after updates or heavy recent usage.

## Workflow

1. Run the audit first:

```bash
python3 scripts/codex_session_recovery.py audit
```

2. If the audit shows local data still exists, preview the repair:

```bash
python3 scripts/codex_session_recovery.py repair
```

3. Apply only after reviewing the dry-run:

```bash
python3 scripts/codex_session_recovery.py repair --apply
```

4. Verify with the backup directory returned by the repair command:

```bash
python3 scripts/codex_session_recovery.py verify --backup-dir <backup_dir>
```

5. If the GUI still fails after a clean local repair, generate a report for an official issue:

```bash
python3 scripts/codex_session_recovery.py report
```

## What This Skill Repairs

- stale `projectless-thread-ids`
- stale `thread-workspace-root-hints`
- missing exact `cwd` roots in saved workspace roots
- missing exact `cwd` roots in project ordering

## Safety Rules

- Do not edit `state_5.sqlite` directly in v1.
- Default to dry-run.
- On write, keep the backup path from the tool output.
- Treat "data missing on disk" and "sidebar not showing the data" as separate diagnoses.

