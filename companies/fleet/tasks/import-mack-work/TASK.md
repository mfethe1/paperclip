---
name: Bring existing Mack work onto the board
slug: import-mack-work
assignee: chief-of-staff
project: control-plane
---

Goal: every live piece of work on Mack has a Paperclip issue in the right project, and
nothing exists only on Mack's disk without an owner.

1. Have Fleet Ops run `scripts/migrate/inventory-local-work.sh` on Mack and attach the
   report. It lists repos with uncommitted changes, unpushed commits, branches with no
   upstream, and stashes. It never pushes.
2. For each repo with unpushed or uncommitted work, open an issue: what the work is,
   which branch, whether it should be pushed, archived, or discarded. Pushing is the
   owner's call. Note that some branches must never go to a public remote.
3. Import open items from `TASK_QUEUE.md` / `BACKLOG.md` files with
   `scripts/migrate/import-task-queue.py`, after a `--dry-run` review.
4. For Hermes Kanban boards and Buzz tasks, list open cards by project and propose the
   mapping in a comment. Don't bulk-import until the authority decision
   (`decide-task-authority`) is approved.

Done when the inventory report shows no unowned work and each imported item links its source.
