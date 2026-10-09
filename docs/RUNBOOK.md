# Runbook

Commands assume a checkout of this repo at `~/paperclip` and use `<mack>` for Mack's
MagicDNS name (`tailscale status` shows it; the real value is kept in the gitignored
`fleet/hosts.json`). `BOARD=https://<mack>.<tailnet>.ts.net:3100`.

Anything that changes a host needs an approved Paperclip approval (or, before the
board exists, Michael's explicit go-ahead) naming the host and the commands.

---

## 1. Install the control plane (Mack)

**Prerequisites**
- Node.js ≥ 24.11 (`node -v`), `jq`, `curl`
- Tailscale logged in, with MagicDNS and HTTPS certificates enabled for the tailnet
  (admin console → DNS). `tailscale serve` needs HTTPS certs.
- Run as the macOS user that owns Claude Code and Codex logins on Mack.

```sh
cd ~/paperclip
scripts/control-plane/install.sh --dry-run   # shows every mutating command
scripts/control-plane/install.sh
```

What it does (idempotent; re-run it any time, e.g. after a Tailscale upgrade drops Serve):
1. Installs `paperclipai@<pinned>` into the managed CLI store (`~/.paperclip/cli`,
   shim at `~/.local/bin/paperclipai`, keeps two rollback versions).
2. First run: `paperclipai onboard --yes --bind tailnet --install-service`. Existing
   instance: leaves data alone and backs up `config.json` before editing.
3. Sets `authenticated/private`, binds to `127.0.0.1:3100`, allows only this node's
   MagicDNS names, and turns telemetry off (`--keep-telemetry` to keep it).
4. `tailscale serve --bg --https=3100 http://127.0.0.1:3100`. It refuses if `:3100` is
   already mapped elsewhere and never touches `:443` (peer-relay) or `:8456` (Buzz).
5. Installs and restarts the LaunchAgent, then verifies through the tailnet URL that
   health is `ok`, the mode is `authenticated`, and anonymous `/api/companies` is not 200.

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

scripts/import-company.py companies/fleet --dry-run
scripts/import-company.py companies/fleet
paperclipai company list --api-base "$PAPERCLIP_API_URL"     # note the company id
```

Do **not** use `paperclipai company import` for this. In 2026.1005.0 it makes
imported routines live immediately. The script imports every agent and routine paused.

## 4. Bring the Mack agents online

For each of Chief of Staff, Builder, Verifier, Fleet Ops:

1. **Credentials.** Claude Code agents use Mack's Claude Code OAuth login (no API keys).
   Codex uses Mack's existing Codex login. If an agent reports an auth error:
   `paperclipai agent claude-login <agent-id>`.
2. **GitHub token for Builder and Verifier.** Create fine-grained tokens scoped to the repos
   they work on, then:
   ```sh
   GH_TOKEN_BUILDER=... paperclipai secrets create -C <company-id> --name gh-token-builder --value-env GH_TOKEN_BUILDER
   ```
   and bind it to the agent's `GH_TOKEN` env input in the agent's settings.
3. **Test environment.** Use the agent's settings page **Test environment** button.
4. **Smoke issue.** Resume the agent (`paperclipai agent resume <agent-id>`), create an
   issue assigned to it ("comment `SMOKE_OK_<timestamp>` and mark done"), and confirm
   the comment and status. Builder's issue should route to the Verifier for review.
5. **Routines** (daily fleet check, weekly review) stay paused until Michael approves
   recurring activation. Then resume them on the Routines page (or `paperclipai routine update`).

## 5. Join a host: Hermes

Enabling Hermes's API server exposes that Hermes to Paperclip-driven runs. On Mack the
gateway (`ai.hermes.gateway`) also runs the production cron registry, so decide first
(in the approval):
- **A. Main gateway:** set `API_SERVER_ENABLED=true` and `API_SERVER_KEY` in the
  gateway's environment. Paperclip runs then see the full Hermes context.
- **B. Separate Hermes install or profile** dedicated to Paperclip work: less blast radius,
  but it doesn't share the main gateway's memory.

On the host:

```sh
# 1. Hermes API server on loopback with a fresh key (store it the way the host stores other
#    Hermes secrets; never in a repo). Hermes processes cannot load launch agents,
#    so a person runs launchctl for plist changes.
export API_SERVER_KEY="$(openssl rand -hex 32)"
API_SERVER_ENABLED=true hermes gateway run --replace --accept-hooks   # or via the host's service unit

# 2. Publish it to the tailnet (HTTPS, same-number port 8642) and verify it rejects anonymous calls
scripts/node/expose-gateway.sh hermes

# 3. Board side (any tailnet machine): create an agent invite
paperclipai invite create -C <company-id> --payload-json '{"allowedJoinTypes":"agent"}' --json | jq -r .token

# 4. On the host: request to join (API_SERVER_KEY still exported)
scripts/node/join-hermes.sh request --paperclip "$BOARD" --invite <token> --name "Hermes (Rosie)"

# 5. Board: approve
paperclipai join approve <request-id> -C <company-id>

# 6. On the host: claim the agent key (saved 0600 under ~/.config/paperclip-fleet/)
scripts/node/join-hermes.sh claim --paperclip "$BOARD" --request <request-id>

# 7. Board: put it in the org chart, then run a smoke issue as in §4
paperclipai agent update <agent-id> --payload-json '{"reportsTo":"<chief-of-staff-id>","title":"Hermes on Rosie","role":"engineer"}'
```

## 6. Join a host: OpenClaw (Rosie)

Rosie's OpenClaw gateway already sits behind Tailscale Serve `:443`.

1. On Rosie: `scripts/node/expose-gateway.sh openclaw`. It confirms gateway auth is set
   (without printing it), reuses the existing Serve mapping, and prints the `wss://` URL.
2. Board → Company settings → Invites → **Generate OpenClaw Invite Prompt** (CLI:
   `paperclipai openclaw invite-prompt -C <company-id> --payload-json '{}'`).
3. Paste the prompt into Rosie's OpenClaw main chat as one message. If it stalls, send:
   "How is onboarding going? Continue setup now."
4. Approve the join request on the board. Check: adapter `openclaw_gateway`, URL is
   `wss://`, token length ≥ 16, device auth enabled (not `disableDeviceAuth`).
5. The first run may need a **device pairing approval inside OpenClaw**. That is separate
   from the Paperclip approval.
6. Smoke issue as in §4, and set `reportsTo`/`title` as in §5 step 7.

## 7. Daily operations

- **Fleet check:** `scripts/fleet-check.sh` (from Mack and from one other node).
  Needs `fleet/hosts.json`: copy `fleet/hosts.example.json` and fill it in.
- **Logs:** `paperclipai service logs -f`; per-run logs are on each issue.
- **Backups:** automatic hourly DB backups with 30-day retention under
  `~/.paperclip/instances/default/data/backups/`. One-off: `paperclipai db:backup`.
  **A backup can only be restored together with `secrets/master.key`.** Copy both
  off-host to an encrypted destination you control, and keep the master key out of git
  and out of chat. There is no `restore` CLI command; restore follows upstream's
  database and secrets docs. Rehearse it once before you rely on it.

## 8. Upgrade Paperclip

1. PR: bump `PAPERCLIP_VERSION` in `scripts/lib/common.sh`. CI imports
   `companies/fleet` into that version. Read the release notes for migrations.
2. On Mack: `paperclipai db:backup`, then
   `paperclipai update --version <new>` and `paperclipai service restart --wait`.
3. `scripts/fleet-check.sh`. If anything regressed: `paperclipai update --rollback`.

## 9. Recovery

| Symptom | Fix |
|---|---|
| Board unreachable after a Mack reboot | FileVault is waiting for an unlock. Unlock remotely. Next time use `sudo fdesetup authrestart` |
| Board fine on Mack's loopback but not on the tailnet | Serve mapping lost (Tailscale upgrades have done this). Re-run `scripts/control-plane/install.sh` |
| `This hostname is not allowed` (403) | Wrong hostname. Use the MagicDNS name, or `paperclipai allowed-hostname <name>` and restart |
| A remote agent's runs fail | `fleet-check.sh` gateway row; fix the host; the next heartbeat retries |
