# paperclip: fleet control plane

Deployment, configuration, and operating rules for running
[Paperclip](https://github.com/paperclipai/paperclip) as the project-management
layer for Michael's agent fleet: Mack, Rosie, Winnie, Airy, and Lenny, connected over
Tailscale.

This repo is **not a fork of Paperclip.** Paperclip is installed as a pinned npm
release (`paperclipai@2026.1005.0`, see `scripts/lib/common.sh`). This repo holds what
is specific to us:

| Path | What it is |
|---|---|
| `companies/fleet/` | The company as code: org chart, agents, projects, routines, and the `fleet-conventions` skill (Agent Companies format, importable) |
| `scripts/control-plane/` | Install and reconcile Paperclip on Mack: authenticated, loopback-only, published on the tailnet via Tailscale Serve |
| `scripts/node/` | Per-host: publish a Hermes/OpenClaw gateway to the tailnet, join it to the board |
| `scripts/migrate/` | Bring existing work in: repo roster → projects, `TASK_QUEUE.md`/`BACKLOG.md` → issues, unpushed-work inventory |
| `scripts/import-company.py` | Import a package with every agent and routine **paused** (the stock CLI starts them live) |
| `scripts/export-company.sh` | Export the live board, normalize it, diff it against `companies/` |
| `scripts/fleet-check.sh` | Probe the control plane, every host, and every gateway from any tailnet node |
| `tools/` | Package validator (mirrors Paperclip's importer and YAML parser), export normalizer |
| `docs/` | [Architecture](docs/ARCHITECTURE.md), [Runbook](docs/RUNBOOK.md), [Project management](docs/PROJECT-MANAGEMENT.md), [Migration](docs/MIGRATION.md), [Security](docs/SECURITY.md) |

## Status

| | State |
|---|---|
| Company package imports cleanly into Paperclip 2026.1005.0 | **Verified** against a live instance; CI repeats it on every PR (`import-smoke` job) |
| Paused import, overlay import, re-import idempotency, export round-trip | **Verified** against a live instance |
| Hermes join flow (invite → request → approve → claim) | **Verified** against a live instance with a stub gateway |
| Control plane installed on Mack | **Not done.** Needs a person on Mack: `scripts/control-plane/install.sh` |
| Remote agents joined (Rosie OpenClaw, Hermes gateways) | **Not done.** Host changes need approval, see `docs/RUNBOOK.md` |
| Which system is the authority for task state (Paperclip vs Buzz/Kanban) | **Open decision.** See [Architecture § Authority](docs/ARCHITECTURE.md#authority-where-each-kind-of-state-lives) |

## Quick start (on Mack)

```sh
git clone https://github.com/mfethe1/paperclip ~/paperclip && cd ~/paperclip
scripts/control-plane/install.sh            # idempotent; --dry-run to preview
# claim the admin in a browser at the printed URL, then:
scripts/control-plane/lock-signup.sh
# import the company, paused:
export PAPERCLIP_API_URL="https://<mack>.<tailnet>.ts.net:3100"
paperclipai auth login --api-base "$PAPERCLIP_API_URL"
export PAPERCLIP_API_KEY="$(paperclipai token board create --name company-import --ttl-days 1 \
  --json --api-base "$PAPERCLIP_API_URL" | jq -r .key.token)"
scripts/import-company.py companies/fleet --dry-run
scripts/import-company.py companies/fleet
```

Then follow [docs/RUNBOOK.md](docs/RUNBOOK.md) to activate agents, join the other
hosts, and bring existing work in ([docs/MIGRATION.md](docs/MIGRATION.md)).

## Repo rules

- **This repository is public.** Never commit secrets, tailnet hostnames or IPs, usernames,
  home paths, or raw exports. Host details live in `fleet/hosts.json` (gitignored);
  exports and migration output live in `exports/` and `migration/out/` (gitignored).
  `tools/validate_company.py` and the gitleaks hook enforce this. See
  [docs/SECURITY.md](docs/SECURITY.md).
- Changes to `companies/fleet/` go through PRs and must pass
  `python3 tools/validate_company.py`.
- Paperclip upgrades are a PR that bumps `PAPERCLIP_VERSION` in `scripts/lib/common.sh`
  (runbook: [Upgrade](docs/RUNBOOK.md#upgrade-paperclip)).

## Checks

```sh
python3 -m pip install pyyaml shellcheck-py   # once
python3 tools/validate_company.py              # company package(s)
python3 -m unittest discover -s tests          # parser/validator/overlay tests
shellcheck scripts/*.sh scripts/*/*.sh
scripts/install-hooks.sh                       # gitleaks + validator pre-commit hook
```
