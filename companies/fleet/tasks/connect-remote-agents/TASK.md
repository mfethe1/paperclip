---
name: Connect agents on the other hosts
slug: connect-remote-agents
assignee: fleet-ops
project: control-plane
---

Bring the agents that run on other hosts onto this board, following
`docs/RUNBOOK.md` ("Join a host"). Host changes are made by Michael at the host, or
after an approval that lists the exact commands per host.

- **Mack, Hermes (decided 2026-10-09: the main gateway, option A).** On Mack:
  `scripts/node/enable-hermes-api.sh --restart`, then
  `scripts/node/expose-gateway.sh hermes`, then `scripts/node/join-hermes.sh request`.
  After board approval, `join-hermes.sh claim --restart`. The claim gives Hermes its
  board key and the `paperclip` and `paperclip-fleet` skills, so it can close its own
  issues and file Telegram requests into Intake.
- **Rosie, OpenClaw:** generate the OpenClaw invite prompt from company settings and
  join as `openclaw_gateway` over `wss://` through Rosie's existing Tailscale Serve front.
- **Winnie:** no SSH execution target (PowerShell-only SSH). Either join its Hermes
  as a gateway once Hermes runs as a service there, or keep Winnie as an inference
  provider only. Propose which.

Each join needs: the gateway rejects unauthenticated requests, the agent completes a
smoke issue (comment a marker, then mark done), and the host alias appears in the
agent's title.
