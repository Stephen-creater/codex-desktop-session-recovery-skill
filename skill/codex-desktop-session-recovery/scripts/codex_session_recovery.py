#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import shutil
import sqlite3
import sys
import tempfile
from collections import Counter, defaultdict
from datetime import datetime, timezone

RECENT_WINDOW = 50
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
        },
        "threads": {
            "active_by_id": active_by_id,
            "all_by_id": all_by_id,
            "cwd_stats": cwd_stats,
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

    next_projectless = sorted(
        thread_id
        for thread_id in current_projectless
        if thread_id in active_by_id and is_projectless_cwd(codex_home, active_by_id[thread_id]["cwd"])
    )
    removed_projectless = sorted(current_projectless - set(next_projectless))

    next_hints: dict[str, str] = {}
    for thread_id in next_projectless:
        thread = active_by_id[thread_id]
        cwd = thread["cwd"]
        hint = current_hints.get(thread_id)
        if hint and (not cwd or is_prefix(hint, cwd)):
            next_hints[thread_id] = hint
        else:
            next_hints[thread_id] = codex_home
    removed_hints = sorted(set(current_hints) - set(next_hints))

    ordered_cwds = sorted(
        cwd_stats.values(),
        key=lambda item: (-item["latest_updated_at"], item["cwd"]),
    )
    discovered_roots = [item["cwd"] for item in ordered_cwds]
    next_saved_roots = dedupe_keep_order(current_saved_roots + discovered_roots)
    next_project_order = dedupe_keep_order(current_project_order + discovered_roots)

    added_saved_roots = [root for root in next_saved_roots if root not in current_saved_roots]
    added_project_order = [root for root in next_project_order if root not in current_project_order]

    return {
        "index": {
            "next_projectless_ids": next_projectless,
            "next_thread_workspace_root_hints": next_hints,
            "removed_projectless_ids": removed_projectless,
            "removed_hint_ids": removed_hints,
        },
        "project_order": {
            "next_saved_roots": next_saved_roots,
            "next_project_order": next_project_order,
            "added_saved_roots": added_saved_roots,
            "added_project_order": added_project_order,
        },
    }


def backup_paths(codex_home: Path, files: list[Path]) -> Path:
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    backup_dir = codex_home / "backups" / "session-recovery" / stamp
    backup_dir.mkdir(parents=True, exist_ok=True)
    for file_path in files:
        if file_path.exists():
            shutil.copy2(file_path, backup_dir / file_path.name)
    return backup_dir


def apply_plan(codex_home: Path, plan: dict, include_index: bool, include_project_order: bool) -> Path:
    state_path = codex_home / ".codex-global-state.json"
    state = load_json(state_path)
    if include_index:
        state["projectless-thread-ids"] = plan["index"]["next_projectless_ids"]
        state["thread-workspace-root-hints"] = plan["index"]["next_thread_workspace_root_hints"]
    if include_project_order:
        state["electron-saved-workspace-roots"] = plan["project_order"]["next_saved_roots"]
        state["project-order"] = plan["project_order"]["next_project_order"]
    backup_dir = backup_paths(codex_home, [state_path])
    write_json_atomic(state_path, state)
    return backup_dir


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
    return "\n".join(lines)


def summarize_plan(plan: dict) -> str:
    index = plan["index"]
    order = plan["project_order"]
    return "\n".join(
        [
            "Planned index repair:",
            f"  remove stale or misclassified projectless ids: {len(index['removed_projectless_ids'])}",
            f"  remove stale thread root hints: {len(index['removed_hint_ids'])}",
            f"  resulting projectless ids: {len(index['next_projectless_ids'])}",
            "Planned project order repair:",
            f"  add saved workspace roots: {len(order['added_saved_roots'])}",
            f"  add project order entries: {len(order['added_project_order'])}",
        ]
    )


def render_report(audit: dict, plan: dict | None = None, backup_dir: str | None = None) -> str:
    counts = audit["counts"]
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
        "## External References",
        "",
    ]
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
        f"  exact saved cwd roots: {b['exact_saved_root_matches']} -> {a['exact_saved_root_matches']}",
        f"  missing exact cwd roots: {b['missing_saved_roots']} -> {a['missing_saved_roots']}",
    ]
    return "\n".join(lines)


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

    repair = sub.add_parser("repair", help="Run both repair steps together.")
    repair.add_argument("--apply", action="store_true", help="Write the repair instead of previewing it.")

    verify = sub.add_parser("verify", help="Verify current state or compare it to a backup.")
    verify.add_argument("--backup-dir", help="Backup directory created by a previous write.")

    report = sub.add_parser("report", help="Generate a Markdown report.")
    report.add_argument("--backup-dir", help="Optional backup directory to mention in the report.")

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

    if args.command in {"repair-index", "repair-project-order", "repair"}:
        include_index = args.command in {"repair-index", "repair"}
        include_order = args.command in {"repair-project-order", "repair"}
        print(summarize_audit(audit))
        print()
        print(summarize_plan(plan))
        if not args.apply:
            print()
            print("Dry-run only. Re-run with --apply to write the repair.")
            return 0
        backup_dir = apply_plan(codex_home, plan, include_index, include_order)
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

    raise AssertionError("unreachable")


if __name__ == "__main__":
    raise SystemExit(main())
