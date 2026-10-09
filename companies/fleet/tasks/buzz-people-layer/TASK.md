---
name: Propose Buzz as the people layer
slug: buzz-people-layer
assignee: chief-of-staff
project: control-plane
---

Decided by Michael on 2026-10-09: Buzz is not a task tracker. It is how agents, and
Paperclip itself, reach the people in the organization: notifications, questions,
and asks that need a person.

Write a one-page proposal (no implementation) covering:

1. **What reaches people through Buzz:** for example, approvals waiting on someone,
   commitments at risk, a question an agent is blocked on, or work handed to a person.
   For each, who receives it and how often.
2. **How it connects:** the options are a Paperclip plugin or webhook that posts to
   Buzz, a routine that summarizes, or the Hermes agent relaying. Name the one you
   recommend and why. Messages link to Paperclip issues and never carry task state.
3. **Replies:** how a person's answer in Buzz gets back onto the issue.
4. **What changes in Buzz:** profiles, channels, and permissions. List the changes;
   making them needs an approval.

Leave it in backlog until the Hermes agent and Telegram intake have run cleanly for
a week.
