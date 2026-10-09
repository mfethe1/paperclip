# Runbook

**Board host: Rosie** (planned; confirm with §0). Mack stays the heavy Hermes worker and
joins the board as an agent. Commands assume this repo is checked out at `~/paperclip`
on each host, and they use `<board-host>` for the board host's MagicDNS name (`tailscale
status` shows it; real names live only in the gitignored `fleet/hosts.json`).
`BOARD=https://<board-host>.<tailnet>.ts.net:3100`.

Anything that changes a host needs an approved Paperclip approval (or, before the
board exists, Michael's explicit go-ahead) naming the host and the commands.
Always `git pull` before re-running a script: fixes land often.

---

## 0. Choose the board host

```sh
cd ~/paperclip && git pull
scripts/control-plane/preflight.sh
```

Read-only. Use a host whose verdict is **ready** and that stays on. Fix FAIL rows first.
On a Mac mini the usual ones are `sudo pmset -a sleep 0` (display sleep is fine) and
`sudo pmset -a autorestart 1`. With FileVault on, an unplanned reboot leaves the board down
until someone unlocks the Mac.

## 1. Install the control plane (board host)

**Prerequisites**
- Node.js ≥ 24.11 **side by side** with the default `node`, which other services may depend
  on (Mack's default is 22). `install.sh` finds Homebrew `node@24` (keg-only), nvm, fnm,
  volta, asdf, or mise. `--install-node` runs `brew install node@24` if none is found.
- `jq`, `curl` (both ship with macOS 15). Tailscale logged in, with MagicDNS and HTTPS
  certificates enabled for the tailnet (admin console → DNS).
- Run it as the macOS user that will own the agents' Claude Code and Codex logins.
  That user must be **logged in to the Mac's desktop** (console or Screen Sharing). The
  background service is a LaunchAgent in that login session; over plain SSH there is
  none, and `install.sh` stops and says so.

```sh
scripts/control-plane/install.sh --dry-run --install-node   # prints every mutating command
scripts/control-plane/install.sh --install-node
```

What it does (idempotent; re-run it any time, e.g. after a Tailscale or Homebrew upgrade):
1. Installs `paperclipai@<pinned>` into the managed CLI store (`~/.paperclip/cli`,
   launcher at `~/.local/bin/paperclipai`, two rollback versions kept).
2. Re-pins the launcher to Homebrew's stable `opt/node@24` path, and gives the server and
   agents a PATH that includes `~/.local/bin` (claude) and Homebrew (codex, gh). launchd's
   default PATH has neither.
3. First run: `paperclipai onboard --yes --bind tailnet --install-service`. Onboard may
   warn that the dashboard is not ready yet; step 4 fixes that. If an instance already
   exists, its data is left alone and `config.json` is backed up before any edit.
4. Sets `authenticated/private`, binds to `127.0.0.1:3100`, allows only this node's
   MagicDNS names, and turns telemetry off (`--keep-telemetry` keeps it).
5. `tailscale serve --bg --https=3100 http://127.0.0.1:3100`. It refuses if `:3100` is
   already mapped elsewhere and never touches other Serve ports (e.g. OpenClaw or
   peer-relay on `:443`).
6. Installs the LaunchAgent (idempotent) and restarts it, requiring the pinned version.
   It then checks on loopback that health is `ok`, the mode is `authenticated`, and an
   anonymous `/api/companies` is not 200. It probes the tailnet URL once; a failure there
   only warns, since a host often can't reach its own tailnet URL. Confirm from another
   node with `scripts/fleet-check.sh`.

If it warns that `paperclipai` isn't on your shell's PATH, add
`export PATH="$HOME/.local/bin:$PATH"` to `~/.zshrc`.

## 2. Claim the instance and lock sign-up

1. On a trusted tailnet device open `$BOARD`, create your account, and choose **Claim this
   instance**. (CLI alternative: `paperclipai auth bootstrap-ceo` prints a one-time URL.)
2. `scripts/control-plane/lock-signup.sh` turns off open sign-up. Invite other people with
   `paperclipai invite create -C <company-id> --payload-json '{"allowedJoinTypes":"human"}'`.

## 3. Import the company (paused)

```sh
export PAPERCLIP_API_URL="$BOARD"
paperclipai auth login --api-base "$PAPERCLIP_API_URL"
export PAPERCLIP_API_KEY="$(paperclipai token board create --name company-import \
  --ttl-days 1 --json --api-base "$PAPERCLIP_API_URL" | jq -r .key.token)"

scripts/import-company.py companies/fleet --dry-run      # plan + env inputs, as JSON
GH_TOKEN_BUILDER=... GH_TOKEN_VERIFIER=... scripts/import-company.py companies/fleet \
  --secret-env agent:builder:GH_TOKEN=GH_TOKEN_BUILDER \
  --secret-env agent:verifier:GH_TOKEN=GH_TOKEN_VERIFIER
paperclipai company list --api-base "$PAPERCLIP_API_URL"    # note the company id
```

- GitHub tokens: use fine-grained tokens scoped to the repos each agent works on. The
  Builder's token needs `contents:write` and `pull_requests:write`; the Verifier's can be
  read-only. Values are read from the environment and never printed. Without
  `--secret-env`, the optional inputs are left unbound. To bind later, create the secret
  with `paperclipai secrets create -C <co> --name gh-token-builder --value-env
  GH_TOKEN_BUILDER --json`, then attach it in the agent's Environment variables editor.
- Re-running is safe: the script refuses to create a second "Fleet" and prints the
  `--company-id <id> --collision skip` form. That form skips issues and routines that
  already exist.
- Don't use `paperclipai company import` for this: in 2026.1005.0 it makes imported
  routines live immediately. The script imports every agent and routine paused.

## 4. Bring the board host's agents online

1. **Logins, as the service user on the board host** (logins are never copied between
   hosts):
   - Claude Code: run `claude`, then `/login`.
   - Codex: `codex login` (ChatGPT), with no `CODEX_HOME` override. Paperclip uses that
     host login.
   - Agents use Claude's ACP engine by default. Set `adapterConfig.engine` to `cli` only
     if you need the CLI lane.
2. **Codex sandbox (decide once).** Paperclip creates `codex_local` agents with
   `dangerouslyBypassApprovalsAndSandbox: true` by default. For the Verifier, decide
   whether to switch it off in the agent's settings, and record the choice in
   docs/SECURITY.md.
3. **Test environment.** Click the button on each agent's settings page.
4. **Smoke issue.** `paperclipai agent resume <agent-id>`, then create an issue assigned
   to it ("comment `SMOKE_OK_<timestamp>` and mark done"). Confirm the comment and status.
   Always resume before assigning. A `todo` or `in_progress` issue assigned to a paused
   agent turns `blocked` within minutes (recovery `stranded_assigned_issue`).
   If it fails, run `scripts/diagnose.sh` (§7). It names the cause and the fix.
5. **Routines** stay paused until Michael approves recurring activation. Then resume the
   routine's assignee agent first, and:
   ```sh
   paperclipai routine list -C <company-id>
   paperclipai routine update <routine-id> --payload-json '{"status":"active"}'
   ```

## 5. Join a host: Hermes (Mack first)

Mack's Hermes is the main worker. Enabling its API server exposes that Hermes to
Paperclip-driven runs. On Mack the gateway (`ai.hermes.gateway`) also runs the
production cron registry, so decide first, in the approval:
- **A. Main gateway:** set `API_SERVER_ENABLED=true` and `API_SERVER_KEY` in the
  gateway's environment. Paperclip runs then see the full Hermes context.
- **B. Separate Hermes install or profile** dedicated to Paperclip work: less blast radius,
  but it doesn't share the main gateway's memory.

```sh
# On the Hermes host. Store the key the way that host stores other Hermes secrets, never
# in a repo. Hermes processes can't load launch agents, so a person runs launchctl.
export API_SERVER_KEY="$(openssl rand -hex 32)"
API_SERVER_ENABLED=true hermes gateway run --replace --accept-hooks   # or via the host's service unit

# Publish it to the tailnet: HTTPS on the same-number port 8642. It refuses to publish a
# gateway that answers without the key.
scripts/node/expose-gateway.sh hermes

# Board side (any tailnet machine): create an agent invite
paperclipai invite create -C <company-id> --payload-json '{"allowedJoinTypes":"agent"}' --json | jq -r .token

# On the Hermes host: request to join (API_SERVER_KEY still exported)
scripts/node/join-hermes.sh request --paperclip "$BOARD" --invite <token> --name "Hermes (Mack)"

# Board: approve
paperclipai join approve <request-id> -C <company-id>

# On the Hermes host: claim the agent key (saved 0600 under ~/.config/paperclip-fleet/)
scripts/node/join-hermes.sh claim --paperclip "$BOARD" --request <request-id>

# Board: put it in the org chart. Check the echoed JSON: misspelled keys are dropped silently.
paperclipai agent update <agent-id> --json --payload-json '{"reportsTo":"<chief-of-staff-id>","title":"Hermes on Mack","role":"engineer"}'
```

Then run a smoke issue as in §4.

## 6. Join a host: OpenClaw (Rosie)

1. On Rosie: `scripts/node/expose-gateway.sh openclaw`. It confirms gateway auth is set
   (without printing it), reuses the existing Serve mapping, and prints the `wss://` URL.
2. Board → Company settings → Invites → **Generate OpenClaw Invite Prompt** (CLI:
   `paperclipai openclaw invite-prompt -C <company-id> --payload-json '{}'`).
3. Paste the prompt into Rosie's OpenClaw main chat as one message. If it stalls, send:
   "How is onboarding going? Continue setup now."
4. Approve the join request on the board. Check: adapter `openclaw_gateway`, the URL
   starts with `wss://` (or `ws://127.0.0.1` when the board runs on Rosie itself), token
   length ≥ 16, and device auth is enabled.
5. The first run may need a **device pairing approval inside OpenClaw**. That is separate
   from the Paperclip approval.
6. Smoke issue as in §4; set `reportsTo`/`title` as in §5.

## 7. Daily operations

- **Agent errors:** `scripts/diagnose.sh` (read-only, GET only, redacted). It groups
  failed runs by cause, prints the fix for each group, and lists recovery actions waiting
  on someone. Add `--server-log <file>` to check for server crashes, and `--out
  report.md` to attach the report to an issue.
  [docs/TROUBLESHOOTING.md](TROUBLESHOOTING.md) has the full table.
- **Commitments:** `scripts/commitments.sh` lists overdue and at-risk projects, `Due:`
  issues, and stalled and blocked work. It is read-only. Add `--strict` to exit 1 when
  anything is overdue or at risk. The weekday routine runs it for you; see
  [Project management § Commitments](PROJECT-MANAGEMENT.md#commitments-and-deadlines).
- **Fleet check:** `scripts/fleet-check.sh`, run from the board host and from one other
  node. Needs `fleet/hosts.json`: copy `fleet/hosts.example.json` and fill it in.
- **Logs:** `paperclipai service logs -n 500` (`-f` to follow); per-run logs are on each issue.
- **Backups:** automatic hourly DB backups with 30-day retention under
  `~/.paperclip/instances/default/data/backups/`. One-off: `paperclipai db:backup`.
  **A backup can only be restored together with `secrets/master.key`.** Copy both
  off-host to an encrypted destination you control, and keep the master key out of git
  and out of chat. There is no `restore` command; restore follows upstream's database
  and secrets docs. Rehearse it once before you rely on it.
- **Board-only configuration** is not in `company export`: per-issue execution policies,
  chat endpoints and their access settings, task watchdogs, tool connections and
  policies, and webhook trigger secrets. Only the database backup preserves it.

## 8. Upgrade Paperclip

1. Wait until the new version is npm `latest`, and read its release notes.
2. PR: bump `PAPERCLIP_VERSION` in `scripts/lib/common.sh`. CI imports `companies/fleet`
   into the new version.
3. On the board host: `git pull`, `paperclipai db:backup`, then
   `scripts/control-plane/install.sh`. It installs the new version, re-pins the launcher,
   and restarts with the expected version. Don't use bare `paperclipai update`: it
   rewrites the launcher without the PATH fix.
4. `scripts/fleet-check.sh` and `scripts/diagnose.sh`. To roll back, revert the pin PR,
   `git pull`, and re-run `install.sh`.

## 9. Recovery

| Symptom | Fix |
|---|---|
| Board unreachable after a reboot of the board host | FileVault is waiting for an unlock. Unlock remotely. Next time use `sudo fdesetup authrestart` |
| `paperclipai` or the service fails with "no such file" for a `.../Cellar/node@24/<old>/bin/node` path | Re-run `scripts/control-plane/install.sh`: it re-pins to Homebrew's stable `opt/node@24` |
| Board briefly down; in-flight runs end as `process_lost` | Probably the upstream stdin-EPIPE crash. launchd restarts the server. Confirm with `scripts/diagnose.sh --server-log <log>`, then re-wake the affected issues |
| Test environment or runs say `claude`/`codex`/`gh` not found | Re-run `install.sh` (re-applies the launcher PATH), then `paperclipai service restart` |
| Issue stays `blocked` or `in_progress` after you fixed credentials | `paperclipai agent resume <agent>`. If `scripts/diagnose.sh` lists a recovery action: `paperclipai issue recovery:resolve <issue> --outcome restored --source-issue-status todo`. Otherwise reassign or comment to re-wake. Check with `paperclipai issue runs <issue>` |
| Board fine on loopback but not on the tailnet | Serve mapping lost (Tailscale upgrades have done this). Re-run `install.sh` |
| `This hostname is not allowed` (403) | Wrong hostname. Use the MagicDNS name, or `paperclipai allowed-hostname <name>` and restart |
| A remote agent's runs fail | `scripts/diagnose.sh` and the `fleet-check.sh` gateway row; fix the host; re-invoke |

## 10. Available but not enabled (each needs Michael's approval)

These exist in 2026.1005.0 and were checked on test instances. Each one needs its
target agent (and routine, if any) resumed first; otherwise calls fail with 409
"not invokable".

| Feature | What it gives the fleet | Constraint | Upstream docs |
|---|---|---|---|
| **Discord chat intake** | Requests in a Discord channel become Intake issues; replies post back | Use a dedicated bot. Lock the endpoint to Michael: no unlinked people, and group chats only if wanted | `doc/CHANNELS.md` |
| **Telegram chat intake** | Same, in the Telegram threads the fleet already uses | Needs a public HTTPS URL, i.e. a Tailscale Funnel limited to `/api/chat-webhooks/`, plus a **new** BotFather bot (never Hermes's bot). Decide the Funnel question first | `doc/CHANNELS.md` |
| **Routine webhooks** | Hermes crons or CI can trigger a Paperclip routine (with HMAC signing) instead of running work themselves | Senders on the tailnet need nothing extra; internet senders need a Funnel limited to `/api/routine-triggers/public/`. Store the one-time secret in the sender's secret store | `docs/api/routines.md` |
| **Task watchdog** | Flags runs that are stuck or silent on long-running umbrella issues | Attach only to in-flight umbrella issues; on a backlog issue it fires immediately. The watchdog agent can't be paused or budget-capped | `doc/TASK-WATCHDOG.md` |
| **Budgets** | Monthly spend caps per agent, with alerts | Set `budgetMonthlyCents` before resuming any agent on a metered API (Hermes or OpenClaw with API keys). Subscription logins report little spend | `docs/guides/board-operator/costs-and-budgets.md` |
