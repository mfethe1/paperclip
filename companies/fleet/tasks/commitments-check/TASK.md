---
name: Commitments check
slug: commitments-check
assignee: chief-of-staff
project: intake
recurring: true
---

Run `scripts/commitments.sh` from the `mfethe1/paperclip` checkout on the board host.
It reads the board and changes nothing. It lists overdue and at-risk commitments,
stalled issues, and blocked issues.

Act on each item it lists. Read the issue's comments first, and nudge any one issue at
most once a day.

1. **Overdue project or overdue `Due:` issue.** Open a Paperclip approval
   (`request_board_approval`) unless one is already pending for it. Include what is
   left, why it slipped, and one recommendation: a new date, or the scope to cut to
   keep the date. Never change a target date yourself.
2. **At-risk project** (due within 14 days). Handle each listed risk:
   - *blocked issue*: comment asking its owner for the exact unblock. If the unblock
     is a board decision, add it to the approval in step 1, or open one.
   - *owned by a paused or failing agent*: tell Michael in your summary which agent
     needs resuming or fixing; `scripts/diagnose.sh` names the cause. Don't reassign
     work away from a paused agent without asking.
   - *nothing in progress*: comment on the highest-priority open issue, mentioning its
     assignee (a comment wakes the assignee). If the issue has no assignee, propose one.
   - *no lead* or *no issues planned*: ask Michael for a lead, or propose the first
     three issues with acceptance criteria.
3. **Stalled issue** (in progress or in review, idle 3+ days). Comment once and ask for
   `DID / NEXT / NEED`. If you already asked two days ago and nothing changed, set it
   `blocked` with an unblock owner and action, and tell the project lead.
4. **Not tracked as commitments.** Weekly at most, ask Michael for target dates on
   active projects that are not ongoing work.

Finish with one comment on this issue: the report's summary line, then one line per
action you took (issue and what you did). If the report says ON TRACK, just say so.
