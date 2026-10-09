---
name: Retire Hermes Kanban for project work
slug: retire-hermes-kanban
assignee: chief-of-staff
project: control-plane
---

Decided by Michael on 2026-10-09: Paperclip replaces Hermes Kanban for project work.
Hermes cron jobs that maintain hosts can stay in Hermes cron.

Prerequisite: the Hermes agent from Mack has joined the board (`connect-remote-agents`).

1. Create a child issue for the Hermes agent. It exports every **open** Kanban card
   to JSON (the format is in its `paperclip-fleet` skill, §4) and reports the file
   path and the card count per board. It does not change the Kanban.
2. Propose the mapping in a comment: which board goes to which Paperclip project, and
   which cards to drop as stale. Michael confirms it.
3. Michael imports it with a board key, after reviewing the dry run:
   `scripts/migrate/build-overlay.py --cards <file> --out exports/kanban-overlay`, then
   `scripts/import-company.py exports/kanban-overlay --company-id <id> --include projects,issues --collision skip --dry-run`,
   then the same command without `--dry-run`. Imported cards land unassigned, in
   backlog (triage) or todo, each with its source card.
4. Triage what landed: owner, project, acceptance criteria, or close with a reason.
5. Open an approval to freeze the Kanban boards. Hermes marks each board read-only with
   a note pointing to Paperclip, and turns off any Kanban-only crons, one at a time.
   Nothing is deleted.

Done when every open card is either an issue on the board or closed with a reason,
and the boards say they are frozen.
