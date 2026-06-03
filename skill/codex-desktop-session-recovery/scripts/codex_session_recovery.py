#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import plistlib
import shutil
import sqlite3
import subprocess
import sys
import tempfile
from collections import Counter, defaultdict
from datetime import datetime, timezone

RECENT_WINDOW = 50
WATCHDOG_LABEL = "com.stephen.codex-session-recovery"
DEFAULT_WATCHDOG_INTERVAL = 1800
EXTERNAL_ISSUES = [
    "https://developers.openai.com/codex/app/features",
    "https://developers.openai.com/codex/memories",
    "https://developers.openai.com/codex/skills",
    "https://github.com/openai/codex/issues/23979",
    "https://github.com/openai/codex/issues/20833",
    "https://github.com/openai/codex/issues/21128",
    "https://github.com/openai/codex/issues/22796",
    "https://github.com/openai/codex/issues/24364",
]


def normalize_path(value: str | None) -> str:
    if not value:
        return ""
    return os.path.abspath(os.path.expanduser(value))


def is_prefix(prefix: str, path: str) -> bool:
    prefix = normalize_path(prefix).rstrip("/")
    path = normalize_path(path)
    return path == prefix or path.startswith(prefix + "/")


def is_projectless_cwd(codex_home: str, cwd: str) -> bool:
    cwd = normalize_path(cwd)
    if not cwd:
        return True
    home = normalize_path(codex_home)
    return cwd == home or is_prefix(home, cwd)


def load_json(path: Path) -> dict:
    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def write_json_atomic(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile("w", delete=False, dir=path.parent, encoding="utf-8") as handle:
        json.dump(payload, handle, ensure_ascii=False, indent=2)
        handle.write("\n")
        tmp_path = Path(handle.name)
    tmp_path.replace(path)


def load_threads(db_path: Path) -> list[dict]:
    con = sqlite3.connect(db_path)
    con.row_factory = sqlite3.Row
    try:
        rows = con.execute(
            """
            select
              id,
              rollout_path,
              created_at,
              updated_at,
              source,
              model_provider,
              cwd,
              title,
              archived
            from threads
            order by updated_at desc, id desc
            """
        ).fetchall()
    finally:
        con.close()
    return [dict(row) for row in rows]


def load_session_index(path: Path) -> dict[str, dict]:
    entries: dict[str, dict] = {}
    if not path.exists():
        return entries
    with path.open("r", encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if not line:
                continue
            item = json.loads(line)
            thread_id = item.get("id")
            if thread_id:
                entries[thread_id] = item
    return entries


def iso_from_unix(seconds: int | float | str | None) -> str:
    if seconds is None:
        return ""
    return datetime.fromtimestamp(int(seconds), tz=timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def write_session_index(path: Path, entries: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile("w", delete=False, dir=path.parent, encoding="utf-8") as handle:
        for entry in entries:
            handle.write(json.dumps(entry, ensure_ascii=False))
            handle.write("\n")
        tmp_path = Path(handle.name)
    tmp_path.replace(path)


def dedupe_keep_order(items: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for item in items:
        item = normalize_path(item)
        if not item or item in seen:
            continue
        seen.add(item)
        result.append(item)
    return result


def choose_workspace_root(cwd: str, saved_roots: list[str]) -> str:
    cwd = normalize_path(cwd)
    candidates = [root for root in saved_roots if is_prefix(root, cwd)]
    if candidates:
        candidates.sort(key=len, reverse=True)
        return candidates[0]
    return cwd


def collect_audit(codex_home: Path, recent_limit: int = RECENT_WINDOW, state_override: dict | None = None) -> dict:
    codex_home = codex_home.expanduser()
    db_path = codex_home / "state_5.sqlite"
    session_index_path = codex_home / "session_index.jsonl"
    state_path = codex_home / ".codex-global-state.json"
    state = state_override if state_override is not None else load_json(state_path)
    threads = load_threads(db_path)
    session_index = load_session_index(session_index_path)

    active = [thread for thread in threads if not thread["archived"]]
    active_by_id = {thread["id"]: thread for thread in active}
    all_by_id = {thread["id"]: thread for thread in threads}

    saved_roots = dedupe_keep_order(state.get("electron-saved-workspace-roots", []))
    project_order = dedupe_keep_order(state.get("project-order", []))
    projectless_ids = set(state.get("projectless-thread-ids", []))
    hints = {key: normalize_path(value) for key, value in state.get("thread-workspace-root-hints", {}).items() if value}

    rollout_missing = []
    session_index_missing = []
    projectless_nonchat = []
    projectless_missing_hint = []
    projectless_bad_hint = []
    external_threads = []
    cwd_stats: dict[str, dict] = {}

    for thread in active:
        thread_id = thread["id"]
        cwd = normalize_path(thread["cwd"])
        thread["cwd"] = cwd
        if thread["rollout_path"] and not Path(thread["rollout_path"]).expanduser().exists():
            rollout_missing.append(thread_id)
        if thread_id not in session_index:
            session_index_missing.append(thread_id)
        if not is_projectless_cwd(str(codex_home), cwd):
            external_threads.append(thread)
            stats = cwd_stats.setdefault(
                cwd,
                {
                    "cwd": cwd,
                    "count": 0,
                    "latest_updated_at": 0,
                    "thread_ids": [],
                },
            )
            stats["count"] += 1
            stats["latest_updated_at"] = max(stats["latest_updated_at"], int(thread["updated_at"]))
            stats["thread_ids"].append(thread_id)
        if thread_id in projectless_ids:
            if not is_projectless_cwd(str(codex_home), cwd):
                projectless_nonchat.append(thread_id)
            hint = hints.get(thread_id)
            if not hint:
                projectless_missing_hint.append(thread_id)
            elif cwd and not is_prefix(hint, cwd):
                projectless_bad_hint.append(thread_id)

    recent_threads = active[:recent_limit]
    recent_cwds = {thread["cwd"] for thread in recent_threads if thread["cwd"]}
    recent_cutoff = recent_threads[-1]["updated_at"] if recent_threads else None
    hidden_cwd_count = len([cwd for cwd in cwd_stats if cwd not in recent_cwds])
    visible_recent_cwd_count = len(recent_cwds)
    exact_saved_root_matches = sum(1 for cwd in cwd_stats if cwd in saved_roots)
    missing_saved_roots = [cwd for cwd in cwd_stats if cwd not in saved_roots]
    hidden_project_samples = [
        item["cwd"]
        for item in sorted(cwd_stats.values(), key=lambda item: (-item["latest_updated_at"], item["cwd"]))
        if item["cwd"] not in recent_cwds
    ][:20]
    heavy_recent_projects = [
        {"cwd": cwd, "count": count}
        for cwd, count in Counter(thread["cwd"] for thread in recent_threads if thread["cwd"]).most_common(10)
    ]

    return {
        "codex_home": str(codex_home),
        "counts": {
            "threads_total": len(threads),
            "threads_active": len(active),
            "external_project_threads": len(external_threads),
            "distinct_external_cwds": len(cwd_stats),
            "session_index_entries": len(session_index),
            "saved_roots": len(saved_roots),
            "project_order": len(project_order),
            "projectless_thread_ids": len(projectless_ids),
            "thread_workspace_root_hints": len(hints),
            "rollout_missing": len(rollout_missing),
            "session_index_missing": len(session_index_missing),
            "projectless_nonchat": len(projectless_nonchat),
            "projectless_missing_hint": len(projectless_missing_hint),
            "projectless_bad_hint": len(projectless_bad_hint),
            "recent_window_threads": len(recent_threads),
            "recent_window_distinct_cwds": visible_recent_cwd_count,
            "projects_hidden_if_recent_only": hidden_cwd_count,
            "exact_saved_root_matches": exact_saved_root_matches,
            "missing_saved_roots": len(missing_saved_roots),
        },
        "state": {
            "saved_roots": saved_roots,
            "project_order": project_order,
            "projectless_ids": sorted(projectless_ids),
            "thread_workspace_root_hints": hints,
        },
        "evidence": {
            "recent_cutoff_updated_at": recent_cutoff,
            "rollout_missing": rollout_missing,
            "session_index_missing": session_index_missing,
            "projectless_nonchat": projectless_nonchat,
            "projectless_missing_hint": projectless_missing_hint,
            "projectless_bad_hint": projectless_bad_hint,
            "missing_saved_roots": missing_saved_roots[:200],
            "recent_cwd_counts": Counter(thread["cwd"] for thread in recent_threads if thread["cwd"]).most_common(20),
            "hidden_project_samples": hidden_project_samples,
            "heavy_recent_projects": heavy_recent_projects,
        },
        "threads": {
            "active_by_id": active_by_id,
            "all_by_id": all_by_id,
            "cwd_stats": cwd_stats,
        },
        "session_index": {
            "entries_by_id": session_index,
        },
    }


def build_repair_plan(audit: dict) -> dict:
    codex_home = audit["codex_home"]
    state = audit["state"]
    active_by_id = audit["threads"]["active_by_id"]
    cwd_stats = audit["threads"]["cwd_stats"]

    current_projectless = set(state["projectless_ids"])
    current_hints = dict(state["thread_workspace_root_hints"])
    current_saved_roots = list(state["saved_roots"])
    current_project_order = list(state["project_order"])

    ordered_cwds = sorted(
        cwd_stats.values(),
        key=lambda item: (-item["latest_updated_at"], item["cwd"]),
    )
    discovered_roots = [item["cwd"] for item in ordered_cwds]
    next_saved_roots = dedupe_keep_order(current_saved_roots + discovered_roots)
    next_project_order = dedupe_keep_order(current_project_order + discovered_roots)

    added_saved_roots = [root for root in next_saved_roots if root not in current_saved_roots]
    added_project_order = [root for root in next_project_order if root not in current_project_order]

    next_projectless = sorted(
        thread_id
        for thread_id, thread in active_by_id.items()
        if is_projectless_cwd(codex_home, thread["cwd"])
    )
    removed_projectless = sorted(current_projectless - set(next_projectless))
    added_projectless = sorted(set(next_projectless) - current_projectless)

    next_hints: dict[str, str] = {}
    for thread_id, thread in active_by_id.items():
        cwd = thread["cwd"]
        if is_projectless_cwd(codex_home, cwd):
            continue
        next_hints[thread_id] = choose_workspace_root(cwd, next_saved_roots)
    removed_hints = sorted(set(current_hints) - set(next_hints))
    added_hints = sorted(set(next_hints) - set(current_hints))
    changed_hints = sorted(
        thread_id for thread_id in set(next_hints).intersection(current_hints) if next_hints[thread_id] != current_hints[thread_id]
    )

    return {
        "index": {
            "next_projectless_ids": next_projectless,
            "next_thread_workspace_root_hints": next_hints,
            "removed_projectless_ids": removed_projectless,
            "added_projectless_ids": added_projectless,
            "removed_hint_ids": removed_hints,
            "added_hint_ids": added_hints,
            "changed_hint_ids": changed_hints,
        },
        "project_order": {
            "next_saved_roots": next_saved_roots,
            "next_project_order": next_project_order,
            "added_saved_roots": added_saved_roots,
            "added_project_order": added_project_order,
        },
    }


def build_session_index_plan(audit: dict) -> dict:
    active_by_id = audit["threads"]["active_by_id"]
    current_entries = audit["session_index"]["entries_by_id"]
    next_entries = []
    missing_ids = []
    stale_ids = []
    for thread in sorted(active_by_id.values(), key=lambda item: (-int(item["updated_at"]), item["id"])):
        current = current_entries.get(thread["id"], {})
        next_entry = dict(current) if current else {}
        next_entry["id"] = thread["id"]
        next_entry["thread_name"] = thread["title"]
        next_entry["updated_at"] = iso_from_unix(thread["updated_at"])
        next_entries.append(next_entry)
        if not current:
            missing_ids.append(thread["id"])
        elif current.get("thread_name") != next_entry["thread_name"] or current.get("updated_at") != next_entry["updated_at"]:
            stale_ids.append(thread["id"])
    return {
        "next_entries": next_entries,
        "missing_ids": missing_ids,
        "stale_ids": stale_ids,
    }


def backup_paths(codex_home: Path, files: list[Path]) -> Path:
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    backup_dir = codex_home / "backups" / "session-recovery" / stamp
    backup_dir.mkdir(parents=True, exist_ok=True)
    for file_path in files:
        if file_path.exists():
            shutil.copy2(file_path, backup_dir / file_path.name)
    return backup_dir


def backup_sqlite_database(db_path: Path, backup_dir: Path) -> Path:
    backup_target = backup_dir / db_path.name
    source = sqlite3.connect(str(db_path))
    dest = sqlite3.connect(str(backup_target))
    try:
        source.backup(dest)
    finally:
        dest.close()
        source.close()
    return backup_target


def apply_plan(
    codex_home: Path,
    plan: dict,
    include_index: bool,
    include_project_order: bool,
    session_index_plan: dict | None = None,
    include_session_index: bool = False,
) -> Path:
    state_path = codex_home / ".codex-global-state.json"
    session_index_path = codex_home / "session_index.jsonl"
    state = load_json(state_path)
    if include_index:
        state["projectless-thread-ids"] = plan["index"]["next_projectless_ids"]
        state["thread-workspace-root-hints"] = plan["index"]["next_thread_workspace_root_hints"]
    if include_project_order:
        state["electron-saved-workspace-roots"] = plan["project_order"]["next_saved_roots"]
        state["project-order"] = plan["project_order"]["next_project_order"]
    backup_targets = [state_path]
    if include_session_index:
        backup_targets.append(session_index_path)
    backup_dir = backup_paths(codex_home, backup_targets)
    write_json_atomic(state_path, state)
    if include_session_index and session_index_plan is not None:
        write_session_index(session_index_path, session_index_plan["next_entries"])
    return backup_dir


def repair_needed(audit: dict) -> bool:
    counts = audit["counts"]
    return any(
        [
            counts["projectless_nonchat"] > 0,
            counts["missing_saved_roots"] > 0,
            counts["projectless_thread_ids"] > 0,
            counts["thread_workspace_root_hints"] != counts["external_project_threads"],
            counts["session_index_missing"] > 0,
        ]
    )


def default_watchdog_paths() -> tuple[Path, Path]:
    home = Path.home()
    return (
        home / "Library" / "LaunchAgents" / f"{WATCHDOG_LABEL}.plist",
        home / ".codex" / "log" / "codex-session-recovery-watchdog.log",
    )


def render_watchdog_plist(script_path: Path, codex_home: Path, interval_seconds: int, log_path: Path) -> bytes:
    python = shutil.which("python3") or "/usr/bin/python3"
    payload = {
        "Label": WATCHDOG_LABEL,
        "ProgramArguments": [
            python,
            str(script_path),
            "--codex-home",
            str(codex_home),
            "heal",
            "--apply",
        ],
        "RunAtLoad": True,
        "StartInterval": interval_seconds,
        "WatchPaths": [str(codex_home / ".codex-global-state.json")],
        "StandardOutPath": str(log_path),
        "StandardErrorPath": str(log_path),
        "WorkingDirectory": str(script_path.parent),
    }
    return plistlib.dumps(payload)


def install_watchdog(script_path: Path, codex_home: Path, interval_seconds: int) -> tuple[Path, Path]:
    plist_path, log_path = default_watchdog_paths()
    plist_path.parent.mkdir(parents=True, exist_ok=True)
    log_path.parent.mkdir(parents=True, exist_ok=True)
    plist_path.write_bytes(render_watchdog_plist(script_path, codex_home, interval_seconds, log_path))
    subprocess.run(["launchctl", "bootout", f"gui/{os.getuid()}", str(plist_path)], check=False, capture_output=True, text=True)
    subprocess.run(["launchctl", "bootstrap", f"gui/{os.getuid()}", str(plist_path)], check=True, capture_output=True, text=True)
    subprocess.run(["launchctl", "kickstart", "-k", f"gui/{os.getuid()}/{WATCHDOG_LABEL}"], check=False, capture_output=True, text=True)
    return plist_path, log_path


def uninstall_watchdog() -> Path:
    plist_path, _ = default_watchdog_paths()
    subprocess.run(["launchctl", "bootout", f"gui/{os.getuid()}", str(plist_path)], check=False, capture_output=True, text=True)
    if plist_path.exists():
        plist_path.unlink()
    return plist_path


def summarize_audit(audit: dict) -> str:
    counts = audit["counts"]
    evidence = audit["evidence"]
    lines = [
        f"Codex home: {audit['codex_home']}",
        f"Active threads: {counts['threads_active']} / total {counts['threads_total']}",
        f"Session index entries: {counts['session_index_entries']}",
        f"Rollout files missing: {counts['rollout_missing']}",
        f"Session index missing rows: {counts['session_index_missing']}",
        f"Saved workspace roots: {counts['saved_roots']}",
        f"Project order entries: {counts['project_order']}",
        f"Projectless thread ids: {counts['projectless_thread_ids']}",
        f"Thread workspace root hints: {counts['thread_workspace_root_hints']}",
        f"Misclassified projectless threads: {counts['projectless_nonchat']}",
        f"Recent window threads: {counts['recent_window_threads']} across {counts['recent_window_distinct_cwds']} cwd values",
        f"Projects hidden if sidebar only loads recent window: {counts['projects_hidden_if_recent_only']}",
        f"Exact cwd roots already saved: {counts['exact_saved_root_matches']}",
        f"Missing exact cwd roots: {counts['missing_saved_roots']}",
    ]
    if evidence["recent_cwd_counts"]:
        lines.append("Recent window concentration:")
        for cwd, count in evidence["recent_cwd_counts"][:10]:
            lines.append(f"  {count:>3}  {cwd}")
    if evidence["projectless_nonchat"]:
        lines.append("Sample misclassified projectless thread ids:")
        for thread_id in evidence["projectless_nonchat"][:10]:
            thread = audit["threads"]["active_by_id"][thread_id]
            lines.append(f"  {thread_id}  {thread['cwd']}")
    if evidence["hidden_project_samples"]:
        lines.append("Sample older projects that still depend on the recent-window bug being fixed upstream:")
        for cwd in evidence["hidden_project_samples"][:10]:
            lines.append(f"  {cwd}")
    return "\n".join(lines)


def summarize_plan(plan: dict) -> str:
    index = plan["index"]
    order = plan["project_order"]
    return "\n".join(
        [
            "Planned index repair:",
            f"  remove stale or misclassified projectless ids: {len(index['removed_projectless_ids'])}",
            f"  add projectless ids: {len(index['added_projectless_ids'])}",
            f"  add thread root hints: {len(index['added_hint_ids'])}",
            f"  change thread root hints: {len(index['changed_hint_ids'])}",
            f"  remove stale thread root hints: {len(index['removed_hint_ids'])}",
            f"  resulting projectless ids: {len(index['next_projectless_ids'])}",
            f"  resulting thread root hints: {len(index['next_thread_workspace_root_hints'])}",
            "Planned project order repair:",
            f"  add saved workspace roots: {len(order['added_saved_roots'])}",
            f"  add project order entries: {len(order['added_project_order'])}",
        ]
    )


def summarize_session_index_plan(session_index_plan: dict) -> str:
    return "\n".join(
        [
            "Planned session index repair:",
            f"  add missing session index entries: {len(session_index_plan['missing_ids'])}",
            f"  refresh stale session index entries: {len(session_index_plan['stale_ids'])}",
            f"  resulting session index entries: {len(session_index_plan['next_entries'])}",
        ]
    )


def render_report(audit: dict, plan: dict | None = None, backup_dir: str | None = None) -> str:
    counts = audit["counts"]
    evidence = audit["evidence"]
    lines = [
        "# Codex Desktop Session Visibility Report",
        "",
        "## Summary",
        "",
        f"- Active threads on disk: `{counts['threads_active']}`",
        f"- Misclassified `projectless-thread-ids`: `{counts['projectless_nonchat']}`",
        f"- Distinct external project `cwd` values: `{counts['distinct_external_cwds']}`",
        f"- External project `cwd` values outside the recent window: `{counts['projects_hidden_if_recent_only']}`",
        f"- Exact project roots missing from saved roots: `{counts['missing_saved_roots']}`",
        "",
        "## Local Evidence",
        "",
        "- Threads are being read from `state_5.sqlite`.",
        "- Session index entries are being read from `session_index.jsonl`.",
        "- Project and sidebar classification is being read from `.codex-global-state.json`.",
        "- This tool treats missing sidebar history as a local visibility bug unless the underlying files are actually missing.",
        "",
        "## Likely Failure Modes",
        "",
        "1. Global recent-window hiding: old project threads still exist but are outside the visible recent subset.",
        "2. `projectless-thread-ids` misclassification: normal project threads were flattened into projectless state.",
        "3. Exact `cwd` roots missing from saved workspace roots or project ordering.",
        "",
        "## Sample Impacted Older Projects",
        "",
    ]
    for cwd in evidence["hidden_project_samples"][:10]:
        lines.append(f"- `{cwd}`")
    lines.extend(
        [
            "",
            "## Recent-Window Pressure",
            "",
        ]
    )
    for item in evidence["heavy_recent_projects"][:10]:
        lines.append(f"- `{item['cwd']}` currently occupies `{item['count']}` thread slots in the top recent window")
    lines.extend(["", "## External References", ""])
    for url in EXTERNAL_ISSUES:
        lines.append(f"- {url}")
    if plan is not None:
        lines.extend(
            [
                "",
                "## Planned / Applied Repair",
                "",
                f"- Remove stale or misclassified projectless ids: `{len(plan['index']['removed_projectless_ids'])}`",
                f"- Remove stale root hints: `{len(plan['index']['removed_hint_ids'])}`",
                f"- Add exact project roots to saved workspace roots: `{len(plan['project_order']['added_saved_roots'])}`",
                f"- Add exact project roots to project order: `{len(plan['project_order']['added_project_order'])}`",
            ]
        )
    if backup_dir:
        lines.extend(["", "## Backup", "", f"- Backup directory: `{backup_dir}`"])
    return "\n".join(lines)


def compare_audits(before: dict, after: dict) -> str:
    b = before["counts"]
    a = after["counts"]
    lines = [
        "Verification summary:",
        f"  active threads unchanged: {b['threads_active']} -> {a['threads_active']}",
        f"  session index missing: {b['session_index_missing']} -> {a['session_index_missing']}",
        f"  misclassified projectless threads: {b['projectless_nonchat']} -> {a['projectless_nonchat']}",
        f"  thread workspace root hints: {b['thread_workspace_root_hints']} -> {a['thread_workspace_root_hints']}",
        f"  exact saved cwd roots: {b['exact_saved_root_matches']} -> {a['exact_saved_root_matches']}",
        f"  missing exact cwd roots: {b['missing_saved_roots']} -> {a['missing_saved_roots']}",
    ]
    return "\n".join(lines)


def latest_thread_for_cwd(audit: dict, cwd: str) -> dict | None:
    cwd = normalize_path(cwd)
    matches = [thread for thread in audit["threads"]["active_by_id"].values() if thread["cwd"] == cwd]
    if not matches:
        return None
    matches.sort(key=lambda item: (-int(item["updated_at"]), item["id"]))
    return matches[0]


def surface_project_thread(codex_home: Path, thread_id: str, pin: bool = False) -> Path:
    backup_dir = codex_home / "backups" / "session-recovery" / datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    backup_dir.mkdir(parents=True, exist_ok=True)
    state_path = codex_home / ".codex-global-state.json"
    db_path = codex_home / "state_5.sqlite"
    session_index_path = codex_home / "session_index.jsonl"
    shutil.copy2(state_path, backup_dir / state_path.name)
    if session_index_path.exists():
        shutil.copy2(session_index_path, backup_dir / session_index_path.name)
    backup_sqlite_database(db_path, backup_dir)
    now = int(datetime.now(timezone.utc).timestamp())
    now_ms = now * 1000
    con = sqlite3.connect(str(db_path))
    try:
        con.execute("update threads set updated_at=?, updated_at_ms=? where id=?", (now, now_ms, thread_id))
        con.commit()
        row = con.execute("select id, title from threads where id=?", (thread_id,)).fetchone()
    finally:
        con.close()
    current_entries = load_session_index(session_index_path)
    entry = dict(current_entries.get(thread_id, {}))
    entry["id"] = thread_id
    entry["thread_name"] = row[1] if row else entry.get("thread_name", "")
    entry["updated_at"] = iso_from_unix(now)
    current_entries[thread_id] = entry
    next_entries = sorted(
        current_entries.values(),
        key=lambda item: (item.get("updated_at", ""), item.get("id", "")),
        reverse=True,
    )
    write_session_index(session_index_path, next_entries)
    if pin:
        state = load_json(state_path)
        current = state.get("pinned-thread-ids", [])
        if thread_id not in current:
            state["pinned-thread-ids"] = [thread_id] + current
            write_json_atomic(state_path, state)
    return backup_dir


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Audit and repair Codex Desktop local session visibility state.")
    parser.add_argument("--codex-home", default="~/.codex", help="Codex home directory. Default: ~/.codex")
    sub = parser.add_subparsers(dest="command", required=True)

    audit = sub.add_parser("audit", help="Read-only audit of local Codex session state.")
    audit.add_argument("--json", action="store_true", help="Emit full JSON instead of text.")
    audit.add_argument("--recent-limit", type=int, default=RECENT_WINDOW, help="Recent window size to model.")

    repair_index = sub.add_parser("repair-index", help="Repair projectless ids and thread root hints.")
    repair_index.add_argument("--apply", action="store_true", help="Write the repair instead of previewing it.")

    repair_order = sub.add_parser("repair-project-order", help="Repair saved workspace roots and project ordering.")
    repair_order.add_argument("--apply", action="store_true", help="Write the repair instead of previewing it.")

    repair_session_index = sub.add_parser("repair-session-index", help="Repair session_index.jsonl from active threads.")
    repair_session_index.add_argument("--apply", action="store_true", help="Write the repair instead of previewing it.")

    repair = sub.add_parser("repair", help="Run both repair steps together.")
    repair.add_argument("--apply", action="store_true", help="Write the repair instead of previewing it.")

    heal = sub.add_parser("heal", help="Apply the repair only if the current state needs it.")
    heal.add_argument("--apply", action="store_true", help="Write when a repair is needed. Without this flag, heal behaves like a preview.")

    verify = sub.add_parser("verify", help="Verify current state or compare it to a backup.")
    verify.add_argument("--backup-dir", help="Backup directory created by a previous write.")

    report = sub.add_parser("report", help="Generate a Markdown report.")
    report.add_argument("--backup-dir", help="Optional backup directory to mention in the report.")

    surface = sub.add_parser("surface-project", help="Bump an old project's latest thread into the recent window.")
    surface.add_argument("--cwd", required=True, help="Exact project cwd to surface.")
    surface.add_argument("--pin", action="store_true", help="Also pin the surfaced thread.")
    surface.add_argument("--apply", action="store_true", help="Write the change instead of previewing it.")

    watchdog_print = sub.add_parser("watchdog-print", help="Print a launchd plist for the self-healing watchdog.")
    watchdog_print.add_argument("--interval-seconds", type=int, default=DEFAULT_WATCHDOG_INTERVAL, help="launchd StartInterval value.")

    watchdog_install = sub.add_parser("watchdog-install", help="Install and load a launchd watchdog that runs heal --apply.")
    watchdog_install.add_argument("--interval-seconds", type=int, default=DEFAULT_WATCHDOG_INTERVAL, help="launchd StartInterval value.")

    sub.add_parser("watchdog-uninstall", help="Unload and remove the launchd watchdog.")

    return parser.parse_args()


def load_backup_state(backup_dir: Path) -> dict:
    state_file = backup_dir / ".codex-global-state.json"
    if not state_file.exists():
        state_file = backup_dir / ".codex-global-state.json"
    return load_json(state_file)


def main() -> int:
    args = parse_args()
    codex_home = Path(normalize_path(args.codex_home))
    audit = collect_audit(codex_home)
    plan = build_repair_plan(audit)
    session_index_plan = build_session_index_plan(audit)

    if args.command == "audit":
        if args.json:
            trimmed = {
                "counts": audit["counts"],
                "evidence": audit["evidence"],
            }
            json.dump(trimmed, sys.stdout, ensure_ascii=False, indent=2)
            sys.stdout.write("\n")
        else:
            print(summarize_audit(audit))
        return 0

    if args.command in {"repair-index", "repair-project-order", "repair-session-index", "repair"}:
        include_index = args.command in {"repair-index", "repair"}
        include_order = args.command in {"repair-project-order", "repair"}
        include_session_index = args.command in {"repair-session-index", "repair"}
        print(summarize_audit(audit))
        print()
        print(summarize_plan(plan))
        if include_session_index:
            print()
            print(summarize_session_index_plan(session_index_plan))
        if not args.apply:
            print()
            print("Dry-run only. Re-run with --apply to write the repair.")
            return 0
        backup_dir = apply_plan(
            codex_home,
            plan,
            include_index,
            include_order,
            session_index_plan=session_index_plan,
            include_session_index=include_session_index,
        )
        after = collect_audit(codex_home)
        print()
        print(compare_audits(audit, after))
        print()
        print(f"Applied. Backup written to: {backup_dir}")
        return 0

    if args.command == "heal":
        print(summarize_audit(audit))
        print()
        print(summarize_plan(plan))
        print()
        print(summarize_session_index_plan(session_index_plan))
        if not repair_needed(audit):
            print()
            if len(session_index_plan["missing_ids"]) == 0 and len(session_index_plan["stale_ids"]) == 0:
                print("No repair needed.")
                return 0
            print("Project/root state is healthy, but session index still needs repair.")
        if not args.apply:
            print()
            print("Repair is needed. Re-run with --apply to write the repair.")
            return 0
        backup_dir = apply_plan(
            codex_home,
            plan,
            True,
            True,
            session_index_plan=session_index_plan,
            include_session_index=True,
        )
        after = collect_audit(codex_home)
        print()
        print(compare_audits(audit, after))
        print()
        print(f"Applied. Backup written to: {backup_dir}")
        return 0

    if args.command == "verify":
        if args.backup_dir:
            before_state = load_json(Path(normalize_path(args.backup_dir)) / ".codex-global-state.json")
            before = collect_audit(codex_home, state_override=before_state)
            print(compare_audits(before, audit))
        else:
            print(summarize_audit(audit))
        return 0

    if args.command == "report":
        backup_dir = args.backup_dir
        print(render_report(audit, plan=plan, backup_dir=backup_dir))
        return 0

    if args.command == "surface-project":
        thread = latest_thread_for_cwd(audit, args.cwd)
        if thread is None:
            print(f"No active thread found for cwd: {normalize_path(args.cwd)}")
            return 1
        print(f"Surface candidate thread: {thread['id']}")
        print(f"CWD: {thread['cwd']}")
        print(f"Title: {thread['title']}")
        print(f"Previous updated_at: {iso_from_unix(thread['updated_at'])}")
        if not args.apply:
            print("Dry-run only. Re-run with --apply to bump this thread into the recent window.")
            return 0
        before = collect_audit(codex_home)
        backup_dir = surface_project_thread(codex_home, thread["id"], pin=args.pin)
        after = collect_audit(codex_home)
        print(compare_audits(before, after))
        print(f"Applied. Backup written to: {backup_dir}")
        return 0

    if args.command == "watchdog-print":
        script_path = Path(__file__).resolve()
        plist_bytes = render_watchdog_plist(script_path, codex_home, args.interval_seconds, default_watchdog_paths()[1])
        sys.stdout.buffer.write(plist_bytes)
        return 0

    if args.command == "watchdog-install":
        script_path = Path(__file__).resolve()
        plist_path, log_path = install_watchdog(script_path, codex_home, args.interval_seconds)
        print(f"Installed watchdog: {plist_path}")
        print(f"Watchdog log: {log_path}")
        return 0

    if args.command == "watchdog-uninstall":
        plist_path = uninstall_watchdog()
        print(f"Removed watchdog: {plist_path}")
        return 0

    raise AssertionError("unreachable")


if __name__ == "__main__":
    raise SystemExit(main())
