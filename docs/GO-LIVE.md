# Go-live checklist

The goal: the board runs on Rosie, its four agents take work, Hermes on Mack works
from the same board, a Telegram request becomes an issue, and every commitment has a
date and a lead that the board watches. The details for each step are in
[RUNBOOK.md](RUNBOOK.md); this page is the order to do them in, and how to tell each
one worked.

Decisions this follows (2026-10-09):
- Paperclip tracks all work, and Hermes Kanban is retired.
- Buzz is the people layer.
- Mack's main Hermes gateway joins the board.
- The Verifier stays sandboxed.
- Telegram intake goes through Hermes.

## Have these ready

Only you can do these:

- [ ] **Time at Rosie's desktop** (in person or Screen Sharing), logged in as the user who
      will own the agents. The board runs as a LaunchAgent in that login session.
- [ ] **Tailscale admin console:** MagicDNS and HTTPS certificates on. Preflight checks this.
- [ ] **Claude Code and Codex** accounts to log in to on Rosie.
- [ ] Optional: **two fine-grained GitHub tokens**, scoped to the repos the agents work on.
      The Builder's needs `contents:write` and `pull_requests:write`; the Verifier's is read-only.
- [ ] **Your commitments:** each project with a real date, plus who leads it. A list in a
      message is enough.
- [ ] **A quiet minute on Mack** to restart Hermes. Chats and cron runs pause for a few seconds.

## 1. Rosie: the board (about an hour)

| Step | Command or action | Worked when |
|---|---|---|
| Preflight | `cd ~/paperclip && git pull && scripts/control-plane/preflight.sh` (first time: `git clone https://github.com/mfethe1/paperclip ~/paperclip`) | `Verdict: ready to host the board` |
| Install | `scripts/control-plane/install.sh --install-node` | It ends with `done. Board URL: …` |
| Claim | Open `https://<board-host>.<tailnet>.ts.net:3100` from another device, create your account, **Claim this instance**; then `scripts/control-plane/lock-signup.sh` | You're signed in as the instance admin |
| Import | RUNBOOK §3: log in the CLI, make a one-day board token, `scripts/import-company.py companies/fleet` | 4 agents, 3 projects, 4 issues, 3 routines, all paused |
| Logins | On Rosie: `claude`, then `/login`; `codex login` | Each agent's **Test environment** button passes |
| Agents | One at a time (Chief of Staff, Fleet Ops, Builder, Verifier): `paperclipai agent resume <id>`, then a smoke issue (RUNBOOK §4) | Each smoke issue is `done` with its marker comment |
| Check | `scripts/fleet-check.sh` from Airy, and `scripts/diagnose.sh` on Rosie | No FAIL rows |

**Resume an agent before you assign it work.** Paperclip blocks `todo` or `in_progress`
issues assigned to a paused agent within minutes.

## 2. Commitments (about 15 minutes)

| Step | Command or action | Worked when |
|---|---|---|
| Dates and leads | For each real commitment, create or open the project, set its **target date** and **lead**. A single deliverable with a date can be an issue whose description starts with `Due: YYYY-MM-DD` | — |
| Report | `scripts/commitments.sh` | It lists your dates; the "no target date" line names only ongoing projects |
| Routines | Activate **Commitments check** first, then **Daily fleet check**, then **Weekly portfolio review** (RUNBOOK §4, step 5) | The next weekday at 08:41 ET, the Chief of Staff posts a commitments summary |

## 3. Mack: Hermes joins (about 20 minutes)

RUNBOOK §5, in order:

| Step | Where | Command | Worked when |
|---|---|---|---|
| API server on | Mack | `scripts/node/enable-hermes-api.sh --restart` | `Hermes API server is up ... and requires its key` |
| Publish | Mack | `scripts/node/expose-gateway.sh hermes` | It prints an `https://…:8642` URL; `/v1/capabilities` without the key is not 200 |
| Invite | Rosie | `paperclipai invite create -C <company-id> --payload-json '{"allowedJoinTypes":"agent"}' --json \| jq -r .token` | A token |
| Request | Mack | `scripts/node/join-hermes.sh request --paperclip "$BOARD" --invite <token> --name "Hermes (Mack)"` | A request id |
| Approve | Rosie | `paperclipai join approve <request-id> -C <company-id>` | — |
| Claim | Mack | `scripts/node/join-hermes.sh claim --paperclip "$BOARD" --request <request-id> --restart` | Key and both skills installed; Hermes restarted |
| Place it | Board | Set Reports to = Chief of Staff, Title = "Hermes on Mack" | — |
| Smoke | Board | An issue assigned to Hermes: "comment `SMOKE_OK` and mark done" | Hermes closes it within a couple of minutes |
| Telegram | Telegram | Ask Hermes: "track: renew the company domain by Oct 30" | It replies with an `FLE-…` key; the issue is in Intake, assigned to the Chief of Staff |

## 4. First week: move the work in

- **Mack's local work:** the `import-mack-work` issue (inventory report, then `TASK_QUEUE.md` overlay).
- **Hermes Kanban:** the `retire-hermes-kanban` issue. Hermes exports the open cards,
  you import them (MIGRATION §1d), the Chief of Staff triages them, then the boards are frozen.
- **Rosie's OpenClaw:** RUNBOOK §6.
- Done when: no open Kanban card exists outside Paperclip, and the daily fleet check has
  been green for five days.

## Later

- **Buzz as the people layer:** the `buzz-people-layer` issue. A proposal first.
- **Winnie:** join its Hermes once it runs as a service, or keep it as an inference provider.
- **Budgets:** set them before resuming any agent that uses a metered API key.
- **Repo safety:** give this repo a protected `main` branch, so agent changes arrive as
  reviewed PRs. The default branch today is a working branch.

## If something fails

Run `scripts/diagnose.sh` on Rosie. It names the cause and the fix for agent run
failures. [TROUBLESHOOTING.md](TROUBLESHOOTING.md) covers setup errors.
