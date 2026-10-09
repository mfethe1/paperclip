# Troubleshooting agent errors

Start with `scripts/diagnose.sh` on any tailnet machine logged in to the board. It is
read-only (GET only) and redacts hostnames, paths and IDs. It groups failed runs by the
causes below and prints each group's fix, so you rarely need this page directly.

```sh
export PAPERCLIP_API_URL=https://<board-host>.<tailnet>.ts.net:3100
export PAPERCLIP_API_KEY=<board key>          # agent keys can't read runs
scripts/diagnose.sh                           # add --server-log <file>, --out report.md, --strict
```

Signals were verified against Paperclip 2026.1005.0: by reproducing them on throwaway
instances, or in the release's source. The run-level rows come from
`tools/agent-errors.tsv`, which diagnose.sh reads. Add a row there when you meet a new one.

**Re-wake** means: `paperclipai agent resume <agent>`. Then, if diagnose.sh lists a
recovery action for the issue, run `paperclipai issue recovery:resolve <issue> --outcome
restored --source-issue-status todo`; otherwise reassign or comment on the issue.
Check with `paperclipai issue runs <issue>`.

## Failed agent runs

| Problem | Signal (errorCode / reason / message) | Fix |
|---|---|---|
| Claude Code is not logged in for the service user (claude_local) | `acpx_turn_failed` / msg ~ `Not logged in\|Please run /login` | On the board host, as the user that runs the Paperclip service: run `claude`, then /login. Then re-wake the issue. Each wake fails 3 times (2 retries 30s apart), so one root cause shows as several runs. |
| Claude Code is not logged in for the service user (CLI engine) (claude_local) | `claude_auth_required` | Same fix: run `claude` then /login as the service user on the board host, then re-wake. |
| `claude` is not on the service's PATH | `claude_command_unresolvable` | Re-run scripts/control-plane/install.sh: it re-pins the launcher PATH to include ~/.local/bin and Homebrew. Or set an absolute adapter command on the agent. |
| An agent CLI (claude/codex/gh) is not on the service's PATH | msg ~ `Command not found in PATH` | Re-run scripts/control-plane/install.sh (launcher PATH), then re-wake. Under launchd the PATH is minimal. |
| Codex has no credentials for the service user (codex_local) | `configuration_incomplete` / `codex_credentials_missing` | On the board host, as the service user: `codex login` (ChatGPT), with no CODEX_HOME override; or bind OPENAI_API_KEY to the agent. Confirm with the codex auth-signal row below, then clear the recovery action and re-wake. |
| Codex ChatGPT login expired or was revoked (codex_local) | `refresh_token_(expired\|reused\|invalidated)` | `codex login` again as the service user, then re-wake. |
| Agent configuration is incomplete (a required secret or setting is missing) | `configuration_incomplete` | Read the run error and the issue's recovery action (listed below); bind the missing secret on the agent, then resolve the recovery action and re-wake. |
| The project's repo could not be cloned on the board host | `workspace_validation_failed` / `fallback_agent_home_cwd` | Make `git ls-remote <repoUrl>` succeed as the service user (credentials, CA trust, network); scripts/control-plane/preflight.sh checks every package repo. Then re-wake. |
| Execution workspace could not be prepared | `workspace_validation_failed` | See the run log's 'Failed to prepare' line (shown below when available). |
| Hermes agent points at a plain-HTTP remote URL (hermes_gateway) | `hermes_gateway_plain_http_remote_denied` | Use the https:// Tailscale Serve URL from scripts/node/expose-gateway.sh hermes; never set dangerouslyAllowInsecureRemoteHttp. |
| Hermes gateway unreachable (hermes_gateway) | `hermes_gateway_connect_failed` | Start the Hermes API server on that host and re-run expose-gateway.sh (Serve mappings get lost on Tailscale upgrades); then re-invoke. |
| Hermes gateway rejected the stored key (hermes_gateway) | `hermes_gateway_auth_failed` | The agent's apiKey no longer matches that host's API_SERVER_KEY: update the agent's key (company secret), then re-invoke. |
| OpenClaw wants a device approval (openclaw_gateway) | `openclaw_gateway_pairing_required` | Approve the pending device in OpenClaw on that host (`openclaw devices approve --latest`). If it repeats every run, the agent has no persisted device key: re-join via the OpenClaw invite flow. |
| OpenClaw gateway unreachable (openclaw_gateway) | `openclaw_gateway_request_failed` | Start the OpenClaw gateway and check its Tailscale Serve front; then re-invoke. |
| The agent's ACP session failed | `acpx_turn_failed` | Read the error line below; common causes are provider quota or rate limits and an expired login. Re-wake after fixing it. |
| Run process was lost (server restart or crash) | `process_lost` | If the server-log section shows EPIPE crashes, that's an upstream bug (launchd restarts the server). Otherwise check `paperclipai service logs`. Re-wake affected issues. |
| Run timed out | `(timeout\|timed_out\|adapter_timeout)` | Check the run log for where it stalled; raise timeoutSec on the agent only if the work legitimately needs longer. |

## Board, setup and import

| Symptom | Cause | Fix |
|---|---|---|
| `install.sh`: `Node.js 22.x is too old` | Clone predates the side-by-side Node 24 support | `git pull`, then `install.sh --install-node` (installs keg-only node@24; your default node is untouched) |
| `install.sh`: `paperclipai on PATH ... reports '...'` | Old clone compared the full `--version` output | `git pull` and re-run |
| `install.sh`: `no GUI login session` | The LaunchAgent needs the user logged in to the Mac's desktop | Log in at the console or via Screen Sharing, then re-run |
| Agent shows status `error` and takes no work | A failed run marks the agent error until it is cleared | Fix the cause from the table above, then `paperclipai agent resume <agent>` |
| HTTP 409 `Agent is not invokable in its current state` (also in routine run failures) | Agent paused (imports pause everything by design) or errored | With approval: `paperclipai agent resume <agent>` |
| HTTP 409 `Routine trigger is not active` | Routine paused (imported paused) | Resume its assignee agent first, then `paperclipai routine update <id> --payload-json '{"status":"active"}'` |
| Import: 422 `Required environment values are missing: agent:<slug>:<KEY>` | A required env input had no value | `scripts/import-company.py` now refuses this before anything is created; pass `--secret-env agent:<slug>:<KEY>=<ENVVAR>` |
| A second company "Fleet (2)", or duplicate routines | A re-import without `--company-id` | Delete the duplicate; re-run with `--company-id <id> --collision skip` (the script now refuses the plain re-run) |
| Telegram setup: 422 `A public HTTPS Paperclip URL is required` | The board is tailnet-only; Telegram needs public HTTPS on 443, 80, 88 or 8443 | Use Discord (no inbound exposure needed), or approve a path-limited Tailscale Funnel first |
| Health warning `database_backup_missing` | The first hourly backup hasn't run yet | Expected for about 90 minutes after a fresh start; after that, check `databaseBackup` in `/api/health` |
| `paperclipai doctor`: `Port 3100 is already in use` while health is ok | Doctor doesn't account for the running server | Ignore |
| Board briefly down; all in-flight runs end `process_lost` | Upstream bug: an unhandled stdin EPIPE from a child process crashes the server | launchd restarts it. `diagnose.sh --server-log <log>` counts the crashes; re-wake the affected issues |

