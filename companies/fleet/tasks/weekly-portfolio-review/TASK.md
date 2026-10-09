---
name: Weekly portfolio review
slug: weekly-portfolio-review
assignee: chief-of-staff
project: intake
recurring: true
---

Run `scripts/commitments.sh --horizon 21` from the `mfethe1/paperclip` checkout on the
board host, then post one comment that Michael can read in two minutes:

1. **Commitments**: every project due in the next three weeks, plus anything overdue.
   For each, give the target date, its state (on track, at risk, or late), and the
   one thing that would most change that. Put late items first.
2. **Shipped this week**: per project, with evidence links (PRs, deploy proof).
3. **In flight**: issue, owner, state (implemented/pushed/reviewed/merged/deployed).
4. **Blocked**: what unblocks each one, and who owns the unblock.
5. **Decisions needed**: each as a yes/no question with your recommendation. Include a
   new date or cut scope for every late commitment.
6. **Hygiene**: issues idle more than 3 days, WIP-limit breaches, Intake items older
   than a day, and active projects with no target date or no lead.
