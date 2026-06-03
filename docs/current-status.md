# Current Status

This document is the project’s current checkpoint.

It is intentionally half-open:

- it records real progress
- it records what is still broken
- it does not pretend the bug is solved end-to-end
- it is written so the next person can resume from the real state, not from optimistic assumptions

## Executive Summary

This project **did not fully solve** the original user problem.

What was achieved:

- hidden project rows were restored in Codex Desktop
- multiple local state layers were audited and repaired
- local data loss was ruled out for the investigated projects
- a reusable recovery skill, report flow, and watchdog were built and published
- public evidence and upstream issue context were collected and linked

What was **not** achieved:

- for some older projects, the project row reappears but the project still shows `No chats` / `暂无对话`
- therefore the final UI symptom the user cared about is still not fully resolved

## What We Now Know

### 1. The thread data still exists locally

For the user’s named examples such as:

- `Binance_pm`
- `AI产品 Stephen`
- `web4.ai`

the local thread rows still exist in `~/.codex/state_5.sqlite`.

The rollout JSONL files also still exist under `~/.codex/sessions/...`.

This means the problem is **not primarily data deletion**.

### 2. Several local metadata layers were genuinely broken

During the run, the following were observed and repaired at different stages:

- stale or incomplete `projectless-thread-ids`
- stale or incomplete `thread-workspace-root-hints`
- incomplete `project-order`
- incomplete `electron-saved-workspace-roots`
- incomplete or stale `session_index.jsonl`

These repairs were not imaginary. They materially changed the local state and restored at least some UI behavior.

### 3. Codex Desktop can reintroduce the broken state while running

One of the strongest findings from this run:

- `.codex-global-state.json` was repaired
- later, while Codex Desktop was still running, it reverted back to a broken shape

This strongly suggests the desktop app has an internal in-memory or app-side persistence layer that can overwrite the on-disk repaired state.

This is why the repo now includes a watchdog / self-heal path.

### 4. There are at least two overlapping bug classes

This repo’s evidence now supports two distinct but related problems:

1. **association/index corruption**
   - project/thread mapping layers become incomplete or wrong
   - project rows may disappear or become detached from threads

2. **recent-window / hydration limitation**
   - even when threads exist and mappings are repaired, old project threads may still remain invisible unless they are brought back into the subset the desktop UI hydrates

There may be a third problem on top:

3. **project row exists but project chat list remains empty**
   - this appears related to `thread-workspace-root-hints` and/or another internal UI cache
   - this is the part that remains unresolved

## Concrete Progress Made

The following milestones were completed during this project:

### Local repair tooling

A reusable recovery tool was built with the following commands:

- `audit`
- `repair`
- `repair-session-index`
- `heal`
- `verify`
- `report`
- `watchdog-print`
- `watchdog-install`
- `watchdog-uninstall`
- `surface-project`

### Skill packaging

The work was packaged as a reusable Codex skill and pushed to GitHub:

- [Stephen-creater/codex-desktop-session-recovery-skill](https://github.com/Stephen-creater/codex-desktop-session-recovery-skill)

### Upstream evidence

Relevant public threads and issues were collected, including:

- [openai/codex#23979](https://github.com/openai/codex/issues/23979)
- [openai/codex#21128](https://github.com/openai/codex/issues/21128)
- [openai/codex#22796](https://github.com/openai/codex/issues/22796)

A new evidence comment was also added during this run:

- [comment on #23979](https://github.com/openai/codex/issues/23979#issuecomment-4609681163)

## Current Local State

At the latest verified point in this run, the local CLI audit showed:

- active threads present
- rollout files present
- `session_index.jsonl` rebuilt
- saved workspace roots populated
- project order populated
- `thread-workspace-root-hints` rebuilt

In other words, the visible on-disk state is now **more complete**, not less complete.

That is why the current best judgment is:

- the repo/tooling did not destroy the user’s data
- the remaining problem is inside Codex Desktop’s final UI hydration / display behavior

## Unresolved Problems

These problems remain unresolved:

### A. Some old project rows still show empty chat lists

This is the user’s key remaining complaint, and it is valid.

Even after repairing the visible local state layers, some projects still show:

- `No chats`
- `暂无对话`

### B. The final authoritative UI data source is still unclear

From CLI-visible state we can repair:

- SQLite thread rows
- session index
- global state JSON
- project/root hints

But Codex Desktop appears to also depend on an internal cache or hydration state that is not fully exposed through the stable public/local surfaces used in this repo.

### C. A one-time repair is not a permanent official fix

The watchdog is a practical mitigation, not a product-level resolution.

It reduces damage from recurring local regressions, but it does not prove the desktop UI will always fully recover thread lists for all old projects.

## Best Current Judgment

If the question is:

> “Why is this still not fully fixed?”

the best current answer is:

**Because the last broken layer is very likely inside Codex Desktop’s own internal UI/cache/hydration logic, and that layer is not fully reconstructible from the documented local state surfaces alone.**

That implies:

- the bug is probably real on the official side
- it is probably not fully solved upstream yet
- this repo can mitigate and explain the issue better than it can guarantee a perfect recovery in all cases

## Did This Repo Make Things Worse?

Current evidence does **not** support that conclusion.

Why:

- the named project threads still exist locally
- the local state became more complete, not less complete
- project rows that were previously hidden were restored
- backups were created before writes
- the unresolved symptom matches ongoing public upstream reports

So the honest conclusion is:

- the repo improved local recoverability
- it did not finish the final UI restoration
- it should not be represented as a complete fix

## Temporary Closure Decision

This project is now in a **paused / temporary closure** state.

Reason:

- the remaining gap is likely upstream / official-app-side
- repeated local iteration is now yielding diminishing returns
- the honest thing to do is preserve the current evidence and stop claiming progress beyond what is proven

## Recommended Next Move

If work resumes later, start from this order:

1. Re-run `audit`
2. Confirm whether the app rewrote `.codex-global-state.json` again
3. Check whether the affected project thread IDs still exist in SQLite
4. Compare the project’s thread IDs against `thread-workspace-root-hints`
5. Re-test one project through the minimal `surface-project` flow
6. Re-check the upstream issues for an official fix or new workaround

Until then, this repo should be treated as:

- a real forensic record
- a partial mitigation toolkit
- not a definitive end-to-end solution
