---
name: Connect agents on the other hosts
slug: connect-remote-agents
assignee: fleet-ops
project: control-plane
---

Bring the agents that run on other hosts onto this board, following
`docs/RUNBOOK.md` ("Join a host"):

- **Rosie, OpenClaw:** generate the OpenClaw invite prompt from company settings and
  join as `openclaw_gateway` over `wss://` through Rosie's existing Tailscale Serve front.
- **Hermes on Mack and Rosie (Airy optional):** enable the Hermes API server bound to
  loopback, publish it with `scripts/node/expose-gateway.sh hermes`, and join as
  `hermes_gateway`.
- **Winnie:** no SSH execution target (PowerShell-only SSH). Either join its Hermes
  as a gateway once Hermes runs as a service there, or keep Winnie as an inference
  provider only. Propose which.

Each join needs: the gateway rejects unauthenticated requests, the agent completes a
smoke issue (comment a marker, then mark done), and the host alias appears in the agent's
title. Host changes need an approval listing the exact commands per host.
