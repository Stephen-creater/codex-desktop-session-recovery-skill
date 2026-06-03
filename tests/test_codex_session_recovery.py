from __future__ import annotations

import json
from pathlib import Path
import sqlite3
import tempfile
import unittest
import importlib.util


SCRIPT_PATH = Path(__file__).resolve().parents[1] / "skill" / "codex-desktop-session-recovery" / "scripts" / "codex_session_recovery.py"
SPEC = importlib.util.spec_from_file_location("codex_session_recovery", SCRIPT_PATH)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC and SPEC.loader
SPEC.loader.exec_module(MODULE)


SCHEMA = """
create table threads (
    id text primary key,
    rollout_path text not null,
    created_at integer not null,
    updated_at integer not null,
    source text not null,
    model_provider text not null,
    cwd text not null,
    title text not null,
    sandbox_policy text not null default '',
    approval_mode text not null default '',
    tokens_used integer not null default 0,
    has_user_event integer not null default 0,
    archived integer not null default 0,
    archived_at integer,
    git_sha text,
    git_branch text,
    git_origin_url text,
    cli_version text not null default '',
    first_user_message text not null default '',
    agent_nickname text,
    agent_role text,
    memory_mode text not null default 'enabled',
    model text,
    reasoning_effort text,
    agent_path text,
    created_at_ms integer,
    updated_at_ms integer,
    thread_source text,
    preview text not null default ''
);
"""


class RecoveryTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmpdir = tempfile.TemporaryDirectory()
        self.codex_home = Path(self.tmpdir.name)
        (self.codex_home / "sessions" / "2026" / "06" / "03").mkdir(parents=True)
        con = sqlite3.connect(self.codex_home / "state_5.sqlite")
        con.executescript(SCHEMA)
        rows = [
            (
                "thread-a",
                str(self.codex_home / "sessions" / "2026" / "06" / "03" / "a.jsonl"),
                1,
                100,
                "vscode",
                "openai",
                "/Users/test/Documents/Codex/2026-06-03/foo",
                "foo",
                0,
            ),
            (
                "thread-b",
                str(self.codex_home / "sessions" / "2026" / "06" / "03" / "b.jsonl"),
                2,
                90,
                "vscode",
                "openai",
                "/Users/test/project-real",
                "real",
                0,
            ),
        ]
        con.executemany(
            """
            insert into threads
            (id, rollout_path, created_at, updated_at, source, model_provider, cwd, title, archived)
            values (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            rows,
        )
        con.commit()
        con.close()
        Path(rows[0][1]).write_text("{}\n", encoding="utf-8")
        Path(rows[1][1]).write_text("{}\n", encoding="utf-8")
        with (self.codex_home / "session_index.jsonl").open("w", encoding="utf-8") as handle:
            handle.write(json.dumps({"id": "thread-a", "thread_name": "foo", "updated_at": "2026-06-03T00:00:00Z"}) + "\n")
            handle.write(json.dumps({"id": "thread-b", "thread_name": "real", "updated_at": "2026-06-03T00:00:00Z"}) + "\n")
        state = {
            "electron-saved-workspace-roots": ["/Users/test/project-real"],
            "project-order": ["/Users/test/project-real"],
            "projectless-thread-ids": ["thread-a"],
            "thread-workspace-root-hints": {"thread-a": "/Users/test/Documents/Codex"},
        }
        (self.codex_home / ".codex-global-state.json").write_text(json.dumps(state), encoding="utf-8")

    def tearDown(self) -> None:
        self.tmpdir.cleanup()

    def test_audit_detects_misclassified_projectless_thread(self) -> None:
        audit = MODULE.collect_audit(self.codex_home)
        self.assertEqual(audit["counts"]["threads_active"], 2)
        self.assertEqual(audit["counts"]["projectless_nonchat"], 1)
        self.assertEqual(audit["counts"]["missing_saved_roots"], 1)

    def test_repair_plan_reclassifies_and_adds_exact_root(self) -> None:
        audit = MODULE.collect_audit(self.codex_home)
        plan = MODULE.build_repair_plan(audit)
        self.assertEqual(plan["index"]["removed_projectless_ids"], ["thread-a"])
        self.assertEqual(plan["project_order"]["added_saved_roots"], ["/Users/test/Documents/Codex/2026-06-03/foo"])
        self.assertEqual(plan["index"]["next_thread_workspace_root_hints"]["thread-b"], "/Users/test/project-real")

    def test_session_index_plan_adds_missing_entries(self) -> None:
        audit = MODULE.collect_audit(self.codex_home)
        session_plan = MODULE.build_session_index_plan(audit)
        self.assertEqual(len(session_plan["missing_ids"]), 0)
        self.assertEqual(len(session_plan["next_entries"]), 2)
        self.assertEqual(session_plan["next_entries"][0]["id"], "thread-a")
        self.assertEqual(session_plan["next_entries"][0]["thread_name"], "foo")

    def test_watchdog_plist_contains_heal_command(self) -> None:
        script_path = self.codex_home / "tool.py"
        log_path = self.codex_home / "watchdog.log"
        plist_bytes = MODULE.render_watchdog_plist(script_path, self.codex_home, 1800, log_path)
        payload = MODULE.plistlib.loads(plist_bytes)
        self.assertEqual(payload["Label"], MODULE.WATCHDOG_LABEL)
        self.assertIn("heal", payload["ProgramArguments"])
        self.assertIn("--apply", payload["ProgramArguments"])
        self.assertEqual(payload["StartInterval"], 1800)
        self.assertEqual(payload["WatchPaths"], [str(self.codex_home / ".codex-global-state.json")])

    def test_latest_thread_for_cwd_returns_newest_match(self) -> None:
        audit = MODULE.collect_audit(self.codex_home)
        thread = MODULE.latest_thread_for_cwd(audit, "/Users/test/Documents/Codex/2026-06-03/foo")
        self.assertIsNotNone(thread)
        self.assertEqual(thread["id"], "thread-a")


if __name__ == "__main__":
    unittest.main()
