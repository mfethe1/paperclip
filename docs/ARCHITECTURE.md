# Architecture

## Goal

One board where every project, piece of work, agent, and approval in the fleet is
visible and owned, reachable from any device on the tailnet, with durable execution
that doesn't depend on the operator's laptop.

## Topology

```
                         Tailscale (tailnet, MagicDNS, Serve certs)
   ┌──────────────────────────────────────────────────────────────────────────────┐
   │  Airy (operator laptop)        iPhone            any tailnet browser         │
   │     │ board UI / CLI             │ board UI          │                       │
   │     └──────────────┬─────────────┴───────────────────┘                       │
   │                    ▼  https://<rosie>:3100  (Tailscale Serve → 127.0.0.1:3100)│
   │  ┌──────────────────────────── Rosie: board host ─────────────────────────┐  │
   │  │  Paperclip server (authenticated/private, loopback bind, LaunchAgent)  │  │
   │  │    embedded Postgres + hourly backups · secrets master key · UI        │  │
   │  │    local adapters:  claude_local (Chief of Staff, Builder, Fleet Ops)  │  │
   │  │                     codex_local  (Verifier)                            │  │
   │  │  OpenClaw gateway :18789 (Serve :443) ── openclaw_gateway agent        │  │
   │  └────────────────────────────────────────────────────────────────────────┘  │
   │          │ https://<mack>:8642 (hermes_gateway)   │ https://<winnie>/ollama   │
   │  ┌───────▼──────── Mack: main worker ───────┐  ┌──▼──── Winnie (Windows) ────┐ │
   │  │ Hermes gateway (API on loopback, Serve)  │  │ Ollama (GPU inference)      │ │
   │  │ ~100 Hermes crons, Buzz relay, NATS hub, │  │ Hermes gateway (planned)    │ │
   │  │ peer-relay (:443), Kanban, heavy builds  │  │ no SSH execution target     │ │
   │  └──────────────────────────────────────────┘  └─────────────────────────────┘ │
   │                                         Lenny: spare, read-only probes        │
   └──────────────────────────────────────────────────────────────────────────────┘
```

### Why the board runs on Rosie

- **Keep the board off the busiest machine.** Mack runs Hermes, about 100 crons and
  builds that churn 10–20 GB of disk a day. A full disk or a stuck process there must
  not take the board and its database down with it.
- **Rosie is underused and always on.** It already runs the OpenClaw gateway, which then
  sits next to the board.
- **Mack still does the heavy work.** Its Hermes joins as an agent (`hermes_gateway`)
  and takes issues like any other.
- **Confirm before installing.** `scripts/control-plane/preflight.sh` reports the
  conditions that make a host a good board: free disk, sleep settings, FileVault and
  auto-login, HTTPS certs, logins. With FileVault on, an unplanned reboot leaves the
  board down until someone unlocks the Mac; planned restarts use
  `sudo fdesetup authrestart`. Agents and routines tolerate brief outages, because
  heartbeats resume.

### Why loopback + Tailscale Serve (not `--bind tailnet`)

- Matches the fleet's established exposure pattern: bind to `127.0.0.1` and front with
  `tailscale serve --https=<port>`. Binding straight to the tailnet IP has hung before.
- Real HTTPS certs on the tailnet: secure cookies, mobile/PWA, and the HTTPS that Paperclip
  requires for remote Hermes gateways.
- Paperclip runs in `authenticated/private` mode: login required, open sign-up
  disabled after the admin claims the instance, and only the MagicDNS name allowed as Host.
  An anonymous API call returns 403 (verified).
- **Port 3100, not 443.** Serve `:443` is already taken on several hosts: OpenClaw on
  Rosie, peer-relay on Mack (and `:8456` is Buzz). The installer refuses to overwrite
  any Serve port that proxies somewhere else.

### How each host's agents reach the board

| Runtime | Adapter | Where it executes | How Paperclip reaches it |
|---|---|---|---|
| Claude Code on the board host | `claude_local` | Rosie | child process of the server, using Rosie's own Claude Code login |
| Codex on the board host | `codex_local` | Rosie | child process of the server, using Rosie's own Codex login |
| Hermes (Mack first; Rosie, Winnie, Airy optional) | `hermes_gateway` | that host | HTTPS to the host's Hermes API server, published with Serve (Paperclip rejects plain-HTTP remote Hermes URLs) |
| OpenClaw (Rosie) | `openclaw_gateway` | Rosie | the gateway on the same host, with gateway token and device pairing |
| Winnie | GPU inference now; Hermes gateway later | Winnie | Ollama is already on the tailnet but answers without a key, so it needs one before agents use it. Windows SSH lands in PowerShell 5.1, so Winnie is not a Paperclip SSH execution target; a Hermes gateway run as a scheduled task is the path to agent work there |
| Airy | none durable | — | Board UI/CLI client. Never schedule work that depends on it |

Agents joined from other hosts use the invite → join request → board approval → one-time
key claim flow (`scripts/node/join-hermes.sh`, or the OpenClaw invite prompt). Their
URLs and keys are host-specific and live only in Paperclip's database, never in this repo.

## Authority: where each kind of state lives

The fleet already has a working coordination stack: Buzz (signed Nostr channels and
tasks; the `buzzsystem` profile is the declared control-plane agent), Hermes Kanban
boards, the Mack Hermes bridge, NATS as transport, peer-relay for execution, plus
`TASK_QUEUE.md` files. The fleet's own rule is *don't create a competing queue.*
Adding Paperclip without an authority decision would create exactly that.

**Recommendation** (pending Michael's approval; tracked as the `decide-task-authority` task):

| State | Authority | Notes |
|---|---|---|
| Goals, projects, issues, assignment, review/approval decisions, budgets, routines that wake agents | **Paperclip** | One owner per issue via checkout; reviewer ≠ executor enforced by the execution policy the Chief of Staff sets on each issue at triage; approvals are first-class objects with an audit trail |
| Code | Git/GitHub | PRs are linked to issues as work products |
| Conversation, notifications, presence, signed identity | Buzz, Telegram, Discord | Messages link to Paperclip issues and never carry task state |
| Transport and remote execution | Tailscale, SSH, NATS, peer-relay | Plumbing only; never a source of truth |
| Hermes Kanban, CCR loop board, `TASK_QUEUE.md`, `BACKLOG.md` | **Retired for project work** after migration | Imported via `scripts/migrate/` and frozen; cron-driven host maintenance can stay in Hermes cron |

Why Paperclip rather than keeping Buzz as the authority: Paperclip already implements
what the fleet has been building by hand. That includes org chart and delegation,
checkout-based ownership, review and approval stages that exclude the executor, budgets,
routines with concurrency and catch-up policies, per-run logs, and native adapters for
Hermes, OpenClaw, Claude Code, and Codex. Buzz stays valuable as the messaging and
identity layer. **What would change this recommendation:** if Buzz's signed approvals
bound to chat threads are a hard requirement that Paperclip approvals can't satisfy,
keep Buzz as the approval authority and have Paperclip link to it.

Until the decision is approved, Paperclip runs alongside the existing stack. Nothing
existing is disabled, and imported agents and routines stay paused.

## Failure modes and what handles them

| Failure | Effect | Detection | Recovery |
|---|---|---|---|
| Board host cold boot (FileVault) | Board and its local agents down | `fleet-check.sh` from another node; Tailscale shows the host offline | Remote unlock; `fdesetup authrestart` for planned reboots |
| Mack down or overloaded | Hermes (Mack) runs fail; the board and other agents keep working | `scripts/diagnose.sh` (hermes_gateway_connect_failed); `fleet-check.sh` | Fix Mack; the Chief of Staff reassigns urgent work |
| Tailscale upgrade drops Serve config (has happened) | Board unreachable on tailnet, still fine on loopback | `fleet-check.sh` health row fails | Re-run `scripts/control-plane/install.sh` (idempotent) |
| Hairpin NAT | A host's own URL looks down from itself | Disagreement between nodes | Always confirm from a second node |
| Remote gateway down | Issues assigned to that agent fail their run | Run failure on the issue; `fleet-check.sh` gateway row | Fix the host; Paperclip retries on the next heartbeat |
| DB corruption or bad upgrade | Board state lost | Health `databaseBackup` warnings | Hourly automatic backups (30-day retention); `paperclipai update --rollback` |
| Secret leaks into package | Public exposure | `validate_company.py` + gitleaks in CI and pre-commit | Rotate the secret; purge history |

## Decisions and alternatives considered

- **Fork paperclipai/paperclip vs. config repo.** Upstream is a fast-moving monorepo (more than 15k PRs).
  A fork would need constant rebasing for no gain, because everything we customize is data
  (company package) or deployment (scripts). We pin the npm release instead.
- **`company import` CLI vs. our importer.** The stock CLI (2026.1005.0) has no way to import
  paused, makes routines live immediately, and treats omitted `include` keys as true, so
  an overlay rewrote the company name in testing. `scripts/import-company.py` sends the
  same payload with `pauseAutomations: true` and explicit includes, and skips tasks
  whose title already exists, because the server does not dedupe them.
- **Paperclip's YAML subset.** Paperclip parses frontmatter and `.paperclip.yaml` with
  its own minimal parser. A JSON-formatted sidecar was silently ignored in testing.
  `tools/pcyaml.py` is a line-for-line port, and the validator fails any file that
  Paperclip would read differently from standard YAML.
