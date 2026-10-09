---
name: Decide where task state lives (Paperclip vs Buzz/Kanban)
slug: decide-task-authority
assignee: chief-of-staff
project: control-plane
---

The fleet already tracks work in Buzz tasks (the buzzsystem control-plane profile),
Hermes Kanban boards, the CCR loop board, and several `TASK_QUEUE.md` files. Two
authorities for the same work is the failure mode the fleet docs warn against.

Prepare a one-page proposal for Michael, as a Paperclip approval, covering:

1. The recommendation from `docs/ARCHITECTURE.md`: Paperclip is the authority for
   goals, projects, issues, and approvals; Buzz stays as the signed messaging, presence,
   and notification layer; Hermes Kanban and the file queues are retired for project
   work; NATS and peer-relay stay as transport.
2. An inventory of what currently writes task state where (crons, profiles, scripts),
   with counts of open items.
3. The cutover steps in order. Each step is reversible, and none disables a cron
   until its replacement has run successfully once.
4. What would make you recommend keeping Buzz as the authority instead.

No cron is disabled and no profile is edited until the approval is granted.
