# Community Signals

These community signals support the same conclusion as the local forensic work in this repo: in many cases, Codex Desktop is hiding or misclassifying existing local chats rather than truly deleting them.

## Reddit

- [Codex Desktop bug/workaround: project shows "No chats" but local threads still exist](https://www.reddit.com/r/codex/comments/1tta67d/codex_desktop_bugworkaround_project_shows_no/)
- [Codex Desktop Windows workaround for project chats hidden by the recent-window sidebar bug](https://www.reddit.com/r/codex/comments/1tu6ga8/codex_desktop_windows_workaround_for_project/)
- [Codex desktop hides chats older than a week. I made a small macOS app to browse, search, wake, and move them](https://www.reddit.com/r/codex/comments/1to1tyv/codex_desktop_hides_chats_older_than_a_week_i/)
- [Codex project conversations seem to disappear over time. Is this expected?](https://www.reddit.com/r/codex/comments/1tnby14/codex_project_conversations_seem_to_disappear/)
- [Threads disappearing randomly all the time in Codex](https://www.reddit.com/r/codex/comments/1thlfrj/threads_disappearing_randomly_all_the_time_in/)
- [Warning: Codex macOS app can make sessions look missing in "By Project" view](https://www.reddit.com/r/codex/comments/1tnrvmz/warning_codex_macos_app_can_make_sessions_look/)

Common pattern across these reports:

- the chats still exist locally
- a new or active project can crowd the visible history window
- "By Project" and flat recent views do not consistently agree
- users often recover visibility by waking, archiving, or reclassifying metadata rather than restoring deleted content

## OpenAI Community

- [Did OpenAI Remove "Projects"? All My Chats Are Gone!](https://community.openai.com/t/did-openai-remove-projects-all-my-chats-are-gone/1143486)
- [Introducing the Codex IDE extension](https://community.openai.com/t/introducing-the-codex-ide-extension/1354930)

These are not the same product surface as Codex Desktop local projects, but they reinforce a broader pattern: history/project visibility bugs can present as disappearance even when the underlying data is still recoverable or still searchable.

## Linux Do

- [Codex Desktop（26.422.20832）Mac版更新自带Broswer Use插件](https://linux.do/t/topic/2042240)
- [codex cli bug](https://linux.do/t/topic/2210491?tl=en)

Linux Do did not provide the same volume of directly matching session-loss reports in this pass, but it did surface current Codex Desktop and Codex runtime discussions that help confirm the fast-moving product surface and version churn around the same period.

## Research Note

GitHub issues and direct local state inspection were higher-signal than YouTube for this bug class. YouTube searches during this run did not surface equally specific forensic material about `projectless-thread-ids`, `cwd` exact matching, or recent-window thread loading.
