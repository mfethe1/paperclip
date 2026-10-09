# Architecture

## Goal

One board where every project, piece of work, agent, and approval in the fleet is
visible and owned, reachable from any device on the tailnet, with durable execution
that doesn't depend on the operator's laptop.

## Topology

```
                         Tailscale (tailnet, MagicDNS, Serve certs)
   ┌──────────────────────────────────────────────────────────────────────────────┐
   │                                                                              │
   │  Airy (operator laptop)        iPhone            any tailnet browser         │
   │     │ board UI / CLI             │ board UI          │                       │
   │     └──────────────┬─────────────┴───────────────────┘                       │
   │                    ▼  https://<mack>:3100   (Tailscale Serve → 127.0.0.1:3100)│
   │  ┌─────────────────────────────── Mack (always on) ───────────────────────┐  │
   │  │  Paperclip server (authenticated/private, loopback bind, LaunchAgent)  │  │
   │  │    embedded Postgres + hourly backups · secrets master key · UI        │  │
   │  │    local adapters:  claude_local (Chief of Staff, Builder, Fleet Ops)  │  │
   │  │                     codex_local  (Verifier)                            │  │
   │  │  Hermes gateway  :8642 ── Serve https://<mack>:8642  (hermes_gateway)  │  │
   │  │  existing: Buzz relay, NATS hub, peer-relay (:443 Serve), Kanban, crons │  │
   │  └────────────────────────────────────────────────────────────────────────┘  │
   │          │ wss://<rosie>  (openclaw_gateway)     │ https://<rosie>:8642        │
   │  ┌───────▼──────── Rosie ─────────┐   ┌───────── Winnie (Windows) ─────────┐ │
   │  │ OpenClaw gateway :18789        │   │ Ollama (GPU inference)             │ │
   │  │   (Serve :443 already)         │   │ Claude Code / Codex (interactive)  │ │
   │  │ Hermes (optional gateway)      │   │ no SSH execution target (PS 5.1)   │ │
   │  └────────────────────────────────┘   └────────────────────────────────────┘ │
   │                                         Lenny: spare, read-only probes        │
   └──────────────────────────────────────────────────────────────────────────────┘
```

### Why the control plane runs on Mack

Mack is already designated as the host for durable implementation and execution, and Airy
is explicitly not durable. Mack's caveat: FileVault is on with no autologin, so a
**cold boot leaves Paperclip down until someone unlocks the disk.** Planned restarts
use `sudo fdesetup authrestart`. Unplanned outages are recovered remotely through the
existing remote-desktop path. Every agent and routine tolerates the board
being briefly unreachable, because heartbeats resume.

### Why loopback + Tailscale Serve (not `--bind tailnet`)

- Matches the fleet's established exposure pattern: bind to `127.0.0.1` and front with
  `tailscale serve --https=<port>`. Binding straight to the tailnet IP has hung before.
- Real HTTPS certs on the tailnet: secure cookies, mobile/PWA, and the HTTPS that Paperclip
  requires for remote Hermes gateways.
- Paperclip runs in `authenticated/private` mode: login required, open sign-up
  disabled after the admin claims the instance, and only the MagicDNS name allowed as Host.
  An anonymous API call returns 403 (verified).
- **Port 3100, not 443.** On Mack, Serve `:443` already belongs to peer-relay and
  `:8456` to Buzz. The installer refuses to overwrite any Serve port that proxies
  somewhere else.

### How each host's agents reach the board

| Runtime | Adapter | Where it executes | How Paperclip reaches it |
|---|---|---|---|
| Claude Code on Mack | `claude_local` | Mack | child process of the server |
| Codex on Mack | `codex_local` | Mack | child process of the server |
| Hermes (Mack, Rosie, optionally Airy) | `hermes_gateway` | that host | HTTPS to the host's Hermes API server, published with Serve (Paperclip rejects plain-HTTP remote Hermes URLs) |
| OpenClaw (Rosie) | `openclaw_gateway` | Rosie | `wss://` to Rosie's gateway through its existing Serve front, with gateway token and device pairing |
| Winnie | none at first | — | Windows SSH lands in PowerShell 5.1 and scp/rsync are unreliable, so it is not a Paperclip SSH execution target. Winnie stays an inference provider (Ollama) until a Hermes gateway runs there as a service |
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
| Goals, projects, issues, assignment, review/approval decisions, budgets, routines that wake agents | **Paperclip** | One owner per issue via checkout; reviewer ≠ executor enforced by execution policy; approvals are first-class objects with an audit trail |
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
| Mack cold boot (FileVault) | Board and Mack agents down | `fleet-check.sh` from another node; Tailscale shows Mack offline | Remote unlock; `fdesetup authrestart` for planned reboots |
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
