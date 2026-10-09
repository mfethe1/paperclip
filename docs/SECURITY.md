# Security

## This repository is public

Anything committed here is readable by anyone. Committed content is limited to
deployment code, the company definition, and docs.

**Never commit:**
- secret values: API keys, OAuth tokens, gateway keys (`API_SERVER_KEY`, OpenClaw
  gateway tokens), Paperclip agent or board keys, claim secrets, private keys,
  `secrets/master.key`, database backups
- tailnet identifiers: MagicDNS names, the tailnet suffix, `100.x` addresses
- usernames, home-directory paths, LAN addresses
- raw exports and migration output (they name private repos and include chat references)

**Where those live instead:**

| Item | Location |
|---|---|
| Host inventory | `fleet/hosts.json` (gitignored; template `fleet/hosts.example.json`) |
| Project roster from GitHub | `fleet/projects.json` (gitignored) |
| Exports, overlays | `exports/` (gitignored) |
| Inventory reports | `migration/out/` (gitignored) |
| Agent credentials | Paperclip secrets (`paperclipai secrets create --value-env ...`), bound to agent env inputs |
| Claimed agent keys on a host | `~/.config/paperclip-fleet/` (0600, written by `join-hermes.sh`) |
| The Hermes agent's board key and the Hermes API server key | `~/.hermes/.env` on the Hermes host (0600; backed up before each change) |

**Enforcement:**
- `tools/validate_company.py` fails on token patterns, private keys, tailnet names and
  IPs, and home paths in `companies/`.
- `scripts/install-hooks.sh` installs a pre-commit hook that runs `gitleaks protect --staged`
  and the validator. Hooks aren't cloned, so run it on every fresh checkout.
- CI runs gitleaks over the full history and the validator on every PR.

If a secret is ever committed: rotate it first, then purge it from history. Making the
repo private does not un-leak it.

## Network exposure

- Paperclip runs in `authenticated/private` mode, listens on `127.0.0.1` only, and is
  published to the tailnet with Tailscale Serve (HTTPS). **Never Funnel.**
- Open sign-up is disabled after the admin claims the instance; people join by invite.
- Gateways (Hermes, OpenClaw) bind to loopback and are published with Serve. Neither
  is joined to the board unless an anonymous request is refused
  (`expose-gateway.sh` and `fleet-check.sh` check this).
- Allowed hostnames are limited to the control plane's MagicDNS names; any other `Host`
  gets 403.

## Agent permissions

- Imported agents start **paused**; hires need board approval
  (`requireBoardApprovalForNewAgents: true`).
- The board-host agents cannot create agents, and only the Builder can create skills.
- Destructive, spending, credential, publishing, external-messaging, deploy, merge,
  access-control, and scheduled-activation actions require a Paperclip approval
  (`fleet-conventions` §6).
- Give GitHub tokens per agent, fine-grained, scoped to specific repos: the Builder gets
  `contents:write` and `pull_requests:write`, the Verifier read-only. Bind them at import
  with `scripts/import-company.py --secret-env`.
- **The real merge gate is GitHub.** Agents run `gh`/`git` with their token directly,
  which bypasses Paperclip's tool policies. Require reviews with no bypass on the default
  branch of every repo the Builder touches.
- **Codex sandbox (decided 2026-10-09): the Verifier stays sandboxed.** It runs Codex's
  workspace-write sandbox with network on. It can edit and run tests inside its own
  workspace and reach GitHub, but it can't write anywhere else on the board host
  (`~/.ssh`, launch agents, other repos, Paperclip's own data). The Verifier runs code
  from the PRs it reviews, so it is the agent most exposed to untrusted input. The
  package sets `dangerouslyBypassApprovalsAndSandbox: false` explicitly:
  - The default ACP engine already keeps the sandbox.
  - The setting holds if the engine is switched to `cli`.
  - It also holds if someone recreates the agent in the UI, where Paperclip's default
    is bypass.

  If a review legitimately needs more access, give that issue to the Builder.
- **Claude agents (Builder, Chief of Staff, Fleet Ops) are not OS-sandboxed.**
  Paperclip's filesystem and network confinement needs Bubblewrap, which is
  Linux-only, and the board host is a Mac. Their limits are their instructions, the
  approval rules, per-agent fine-grained GitHub tokens, and branch protection.
- **Hermes's board key** lives in `~/.hermes/.env` on Mack (0600), written by
  `join-hermes.sh claim`, next to Hermes's other keys. It is an agent key, not a board
  key: it can file and read issues, and change an issue only from inside a Paperclip
  run of that agent. Rotate it by revoking the key on the board and re-running the join.
- **Funnel stays off.** Telegram intake goes through Hermes, which polls Telegram, so the
  board needs no public endpoint. If Paperclip's own chat connector or internet webhook
  senders are ever approved, the Funnel is limited to the one path they need
  (`/api/chat-webhooks/` or `/api/routine-triggers/public/`), never the whole board.
