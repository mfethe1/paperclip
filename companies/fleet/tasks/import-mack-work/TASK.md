---
name: Bring existing Mack work onto the board
slug: import-mack-work
assignee: chief-of-staff
project: control-plane
---

Goal: every live piece of work on Mack has a Paperclip issue in the right project, and
nothing exists only on Mack's disk without an owner.

1. Ask Michael (or the Hermes agent that joined from Mack) to run
   `scripts/migrate/inventory-local-work.sh` on Mack and attach the report. Fleet Ops runs
   on the board host and doesn't change other hosts. It lists repos with uncommitted changes, unpushed commits, branches with no
   upstream, and stashes. It never pushes.
2. For each repo with unpushed or uncommitted work, open an issue: what the work is,
   which branch, whether it should be pushed, archived, or discarded. Pushing is the
   owner's call. Note that some branches must never go to a public remote.
3. Import open items from `TASK_QUEUE.md` / `BACKLOG.md` files: build an overlay with
   `scripts/migrate/build-overlay.py`, then load it with `scripts/import-company.py
   exports/overlay --company-id <id> --include projects,issues --collision skip`,
   after reviewing a `--dry-run` (docs/MIGRATION.md, 1b).
4. Hermes Kanban cards move to the board through `retire-hermes-kanban`. Buzz tasks:
   list the open ones and propose which become issues; Buzz itself stays as the
   people layer (`buzz-people-layer`).

Done when the inventory report shows no unowned work and each imported item links its source.
