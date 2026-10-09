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
- Mack agents cannot create agents and only Builder can create skills.
- Destructive, spending, credential, publishing, external-messaging, deploy, merge,
  access-control, and scheduled-activation actions require a Paperclip approval
  (`fleet-conventions` §6).
- Give GitHub tokens per agent, fine-grained, scoped to specific repos. The Verifier gets
  read-only scopes.
