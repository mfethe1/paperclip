---
name: paperclip-fleet
description: Work with Michael's Paperclip board, the fleet's project-management system and the only place work is tracked. Use it when a Paperclip run wakes you, when Michael asks in chat to track, file, or remember something, when he asks what's on his plate or what's late, and when Hermes Kanban work needs moving to the board.
required_environment_variables:
  - PAPERCLIP_API_URL
  - PAPERCLIP_API_KEY
  - PAPERCLIP_COMPANY_ID
  - PAPERCLIP_AGENT_ID
---

# Paperclip for the fleet

Paperclip (on Rosie) is where all work is tracked: goals, projects, issues, owners,
dates. **Hermes Kanban is retired for project work.** Don't create Kanban cards;
file Paperclip issues. Chat (Telegram, Buzz) is for conversation. Link issues there,
but don't keep task state there.

The credentials come from `~/.hermes/.env`: `PAPERCLIP_API_URL` (board base URL,
without `/api`), `PAPERCLIP_API_KEY` (your agent key), `PAPERCLIP_COMPANY_ID`,
`PAPERCLIP_AGENT_ID`. Never print, echo, or paste the key anywhere: not in issues,
comments, chat, or logs.

The scripts below are in this skill's `scripts/` directory. Each one checks the HTTP
status and says plainly when something was NOT done.

## 1. When Paperclip wakes you

A Paperclip run starts with "Paperclip runtime identity" and a Run ID. Follow the
`paperclip` skill's heartbeat steps for the issue named in the wake. Also:

- Do the work in this run. Don't stop at a plan unless the issue asks for one.
- Finish every run with a confirmed status change and a handoff comment:

  ```sh
  scripts/paperclip-issue-update.sh --issue-id FLE-12 --status done --run-id <Run ID> --comment - <<'MD'
  DID:  what you actually did (commands, files, links)
  NEXT: the next concrete step and who owns it
  NEED: decisions or access you're waiting on (or "nothing")
  MD
  ```

  If you're stuck: `--status blocked --unblock-action "<exactly what would unblock it>"`.
  If the script exits non-zero, say in your reply that the update FAILED.
- **Done means verified.** Evidence is something a reviewer can rerun: a command and
  its output, a commit SHA, a PR link. Paperclip routes `done` to a reviewer when the
  issue has one; never review your own work.
- **Ask first** (open a Paperclip approval) before anything destructive, spending
  money, touching credentials, publishing, messaging people outside the fleet,
  deploying, merging to a default branch, or changing crons, launchd jobs, or access.
- Never force-push or push to `main`/`master`. Never commit secrets, tailnet names,
  or IPs.

## 2. Filing work from chat

When Michael asks you to track, file, or "remember to" do something that is more than
a quick answer, file it:

```sh
scripts/paperclip-intake.sh --title "<the outcome, in one line>" [--priority high] [--due 2026-11-30] \
  --description - <<'MD'
What is wanted and why, in Michael's words where possible.
Acceptance: how we'll know it's done (if he said).
Source: Telegram, <date>.
MD
```

It files the issue in **Intake**, assigned to the Chief of Staff for triage. If the
Chief of Staff can't run, it leaves the issue unassigned in backlog. If an open issue
has the same title, it points to that issue instead. Reply with the issue key it
prints. Use `--due` only for a date Michael actually gave; never invent one.

Don't file small talk, questions you can answer now, or things already on the board.

## 3. Answering "what's on my plate" and "what's late"

- **Late or at risk:** run `~/paperclip/scripts/commitments.sh`, the fleet repo's
  read-only report (`git -C ~/paperclip pull` first). Report the bold summary line,
  then the overdue and at-risk rows.
- **Your own queue:** `scripts/paperclip-my-work.sh`. For everyone's open work, add
  `--all-open`.
- Quote issue keys (FLE-123) so Michael can open them.

## 4. Moving Hermes Kanban work to the board

Only when an issue asks you to. Export **open** cards (skip done and archived) to one
JSON file, a list of:

```json
{"title": "...", "body": "...", "status": "triage|todo|ready|running|review|blocked",
 "project": "<board project slug, e.g. intake>", "priority": "low|medium|high|critical",
 "source": "kanban:<board>/<card-id>"}
```

Save it outside any git repo (for example `~/paperclip/exports/kanban-cards.json`;
`exports/` is gitignored). Report the path and the card counts per board. Michael
imports it with a board key (`scripts/migrate/build-overlay.py --cards ...`, then
`scripts/import-company.py`). Don't delete or archive Kanban cards. After he confirms
the import, mark each board read-only with a note pointing to Paperclip.
