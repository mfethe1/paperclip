# Migration: getting existing work onto the board

Phased. Each phase is reversible, and nothing in the existing stack (Buzz, Hermes Kanban,
crons, OpenClaw) is disabled before Phase 3's approval.

## Phase 0: stand up (no existing system touched)

`docs/RUNBOOK.md` §0–4: preflight and install on the board host (Rosie), claim, import
`companies/fleet` paused, bring its four agents online with smoke issues.

## Phase 1: bring the work in

All output goes to `exports/` or `migration/out/` (both gitignored), because it names
private repos and contains chat references.

**1a. Projects from repos** (on any machine with `gh` logged in):
```sh
scripts/migrate/discover-projects.sh --days 60     # writes fleet/projects.json
# edit fleet/projects.json: drop non-projects, merge related repos, fix names;
# add "targetDate": "YYYY-MM-DD" and "lead": "<agent-slug>" to projects with a real date
```

**1b. Backlog from queue files** (on the host that has them, usually Mack):
```sh
scripts/migrate/build-overlay.py \
  --projects fleet/projects.json \
  --checklist ~/openclaw-shared/workspace/TASK_QUEUE.md=intake \
  --checklist <path>/BACKLOG.md=<project-slug> \
  --since 2026-08-01 \
  --out exports/overlay
python3 tools/validate_company.py exports/overlay        # secrets block; host identifiers warn
scripts/import-company.py exports/overlay --company-id <id> \
  --include projects,issues --collision skip --dry-run
scripts/import-company.py exports/overlay --company-id <id> \
  --include projects,issues --collision skip
```
- Only open items (`[ ]`, `[>]`) are imported, unassigned, in `backlog`, each with its
  source file, line, and section. `--since` drops `TASK_QUEUE` items extracted before a date.
- Re-running is safe: tasks whose title already exists are skipped, existing projects are
  skipped, and the company's name and description are never touched by an overlay.

**1c. Work that exists only on Mack's disk:**
```sh
scripts/migrate/inventory-local-work.sh ~            # read-only; report in migration/out/
```
Lists repos and worktrees with uncommitted changes, commits not on any remote, branches
without upstream, and stashes. File one issue per flagged repo. Pushing is the owner's
decision, and some branches (brand/private) must never go to a public remote. Known items
to look for: the FLEET-LEARNING-001 pilot worktree, unpushed Buzz work under
`~/.buzz/REPOS`, and the archived llama.cpp fork commits.

**1d. Hermes Kanban and Buzz tasks:** read-only. The Chief of Staff lists open cards
per board and proposes a mapping (`import-mack-work` task). They are imported in bulk only
after Phase 3 is approved; until then the two systems would both be authoritative.

## Phase 2: connect the other hosts

`docs/RUNBOOK.md` §5–6: OpenClaw on Rosie, Hermes gateways. Each join is one approval
listing the exact host commands.

## Phase 3: cutover (needs approval: `decide-task-authority`)

In order, each step verified before the next:

1. New requests go to Intake (Chief of Staff confirms chat requests become issues).
2. Bulk-import open Kanban cards and Buzz tasks; freeze those boards (read-only notice).
3. Point the notification crons (Telegram threads, Buzz `#fleet`) at Paperclip issue
   links instead of Kanban cards.
4. Disable superseded crons **one at a time**, each only after its Paperclip routine
   replacement has completed successfully at least once.
5. After two clean weeks, archive the old boards.

**Rollback:** re-enable the cron, unfreeze the board. Nothing is deleted during cutover.
