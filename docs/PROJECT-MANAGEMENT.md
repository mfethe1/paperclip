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
- **Intake** is the single front door. Ask Hermes in Telegram to track something, and
  it files an Intake issue assigned to the Chief of Staff, then replies with the
  `FLE-` key (`paperclip-fleet` skill). Other channels file by hand for now. The Chief of
  Staff triages each one within a day: outcome, acceptance criteria, project, priority,
  owner, or close with a reason.

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

Paperclip's execution policy enforces what the fleet previously did by convention, **but
only on issues that carry one.** The policy is a field on each issue. Projects have no
default, child issues don't inherit it, and the company package can't carry it. The
Chief of Staff therefore sets it at triage, whenever it assigns an issue (see its
instructions). The shape is in upstream's `docs/guides/execution-policy.md`.

| Work type | Policy |
|---|---|
| Code change | Review stage: Verifier (or any agent other than the executor). Approval stage: board, for merges to default branches |
| Host or infrastructure change | Approval stage: board, before execution; issue lists host and exact commands |
| Research, docs | Review stage: Chief of Staff |
| Anything in the "ask first" list | Paperclip approval object before acting |

The runtime routes `done` to the next stage and never lets the executor review its own
work. "Changes requested" returns the issue to the same executor. After two identical
failures the issue is blocked; after three review rounds the Chief of Staff re-plans it.

## Commitments and deadlines

Paperclip 2026.1005.0 has a target date on **projects** only. Issues have no due date
(checked in the release's schema). So:

- **A commitment is a project with a target date and a lead.** For a deliverable with
  its own date, make it a project (it can be small), or give the issue a first
  description line `Due: YYYY-MM-DD`.
- **Only Michael sets or moves dates**, in the project's settings or through an approval
  the Chief of Staff opens. Agents say a date is at risk as soon as they know
  (`fleet-conventions` §9).
- **Leads come from `leadAgentSlug`.** In `.paperclip.yaml`, set
  `projects.<slug>.leadAgentSlug`. The importer ignores `owner:` in `PROJECT.md`, and the
  validator rejects a package that relies on it. For overlays, add `targetDate` and
  `lead` to `fleet/projects.json`.

`scripts/commitments.sh` is the read-only view of all of this. Agents run it with
their own key; a person runs it with a board key. Its sections:

| Section | Rule |
|---|---|
| Overdue | Target date or `Due:` date has passed and the work isn't completed |
| Due within the horizon (default 14 days) | **At risk** if it has no lead, no issues, blocked issues, issues owned by a paused or failing agent, nothing in progress, or no activity for 3 days |
| Stalled | `in_progress` or `in_review` with no activity for 3 days |
| Blocked | With the stated unblock, or Paperclip's recovery reason in plain words |
| Not tracked | Active projects with no date or no lead, and ready issues with no owner |

One Paperclip behavior matters here. An issue in `todo` or `in_progress` assigned to a
**paused** agent turns `blocked` within minutes: the recovery sweep marks it stranded and
hands it to the board. Resume an agent before you give it work.

## Limits and cadence

- **WIP:** at most 2 implementation and 3 verification issues `in_progress` per project.
- **Daily:** Fleet Ops runs the fleet check routine (06:47 ET): `fleet-check.sh` for
  hosts and the board, plus `diagnose.sh` for agent run failures.
- **Weekdays:** Chief of Staff runs the commitments check (08:41 ET). It opens an approval
  for each overdue item (a new date, or the scope to cut), nudges stalled and at-risk
  work once a day, and posts a short summary.
- **Weekly:** Chief of Staff posts the portfolio review (Mondays 07:52 ET). It leads with
  commitments for the next three weeks, then covers what shipped (with evidence),
  what's in flight, what's blocked, and the decisions needed.
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
| Reviewer ≠ implementer, max 3 rounds | Execution policy review stage (enforced when set at triage) |
| Approvals bound to a Telegram thread | Paperclip approval objects; chat links to them |
| Branch `<agent>/<task>`, commit `[agent] verb: desc` | Unchanged; the issue key goes in the branch name |
| `FLEET-FEDERATION.md` PR claims | Issue checkout plus the PR linked as a work product |
