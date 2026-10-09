# Project management model

How work is organized on the board. The rules agents follow are in the
`fleet-conventions` skill (`companies/fleet/skills/fleet-conventions/SKILL.md`). This
page explains the model behind them and how existing fleet conventions map onto it.

## Structure

```
Company: Fleet  (goals in COMPANY.md)
 ├─ Project per product or system   (one primary repo workspace each)
 │    e.g. Construct Pro, BidCraft, Buzz, Fleet Operations, Control Plane
 │    └─ Issues  FLE-<n>            (one owner, acceptance criteria, evidence)
 │         └─ Child issues          (split work; never share one issue)
 ├─ Intake                          (everything new lands here; triaged daily)
 └─ Routines                        (recurring work; each run is an issue with an owner)
```

- **Projects map to repos/products**, not to hosts. Host-specific work is an issue in
  Fleet Operations, or an issue assigned to the agent that runs on that host.
- **Intake** is the single front door. Requests from Telegram, Discord, or Buzz become
  Intake issues (by hand at first; via a Paperclip chat connector or routine webhook
  later). The Chief of Staff triages each one within a day: outcome, acceptance criteria,
  project, priority, owner, or close with a reason.

## Lifecycle

| Status | Meaning |
|---|---|
| `backlog` | Captured, not committed. Imported items land here |
| `todo` | Triaged: criteria written, project and owner set |
| `in_progress` | Checked out by its owner (a hard claim) |
| `in_review` | Executor finished; the runtime routed it to the reviewer or approver |
| `blocked` | Waiting on something named in the issue |
| `done` | Every review and approval stage passed |

Report delivery separately from status: **implemented → pushed → reviewed → merged →
deployed → accepted**. An issue is `done` when its acceptance criteria say so. For code
that usually means merged with evidence; for production changes it means deployed and
verified at the expected commit.

## Review and approval (execution policy)

Paperclip's execution policy enforces what the fleet previously did by convention:

| Work type | Policy |
|---|---|
| Code change | Review stage: Verifier (or any agent other than the executor). Approval stage: board, for merges to default branches |
| Host or infrastructure change | Approval stage: board, before execution; issue lists host and exact commands |
| Research, docs | Review stage: Chief of Staff |
| Anything in the "ask first" list | Paperclip approval object before acting |

The runtime routes `done` to the next stage and never lets the executor review its own
work. "Changes requested" returns the issue to the same executor. After two identical
failures the issue is blocked; after three review rounds the Chief of Staff re-plans it.

## Limits and cadence

- **WIP:** at most 2 implementation and 3 verification issues `in_progress` per project.
- **Daily:** Fleet Ops runs the fleet check routine (06:47 ET).
- **Weekly:** Chief of Staff posts the portfolio review (Mondays 07:52 ET), covering what
  shipped (with evidence), what's in flight, what's blocked, and the decisions needed.
- **Budgets:** agents on subscription logins (Claude Code OAuth, Codex) report little or no
  spend. Set budgets on agents that use metered APIs before they run unattended.

## Mapping from existing conventions

| Before | On the board |
|---|---|
| `TASK_QUEUE.md` `- [ ]` / `[>]` lines | `backlog` issues via `scripts/migrate/build-overlay.py` (source line recorded) |
| `BACKLOG.md` checklists and phases | Issues in the matching project; phase headings recorded as source sections |
| Hermes Kanban `triage/todo/ready/running/blocked/review/done` | `backlog/todo/todo/in_progress/blocked/in_review/done` |
| Kanban `running` card = hard claim | Issue checkout |
| Buzz registry `REG-N`, feature IDs (`FLEET-LEARNING-001`) | Keep the old ID in the issue title or body for search; the issue key is `FLE-<n>` |
| DID / NEXT / NEED handoffs | End-of-run comment in the same shape (required by the skill) |
| Reviewer ≠ implementer, max 3 rounds | Execution policy review stage (enforced) |
| Approvals bound to a Telegram thread | Paperclip approval objects; chat links to them |
| Branch `<agent>/<task>`, commit `[agent] verb: desc` | Unchanged; the issue key goes in the branch name |
| `FLEET-FEDERATION.md` PR claims | Issue checkout plus the PR linked as a work product |
