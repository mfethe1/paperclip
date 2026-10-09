---
schema: agentcompanies/v1
name: Fleet
slug: fleet
description: Michael's agent fleet. One board for every project, agent, and host on the tailnet.
version: 0.1.0
license: MIT
authors:
  - name: Michael Fethe
goals:
  - Every piece of agent work is a Paperclip issue with one owner, one project, and evidence-backed completion.
  - Durable work runs on always-on hosts (Mack) and never depends on the operator laptop being awake.
  - Agents on every tailnet host (Hermes, OpenClaw, Claude Code, Codex) take work from the same board.
---

# Fleet

This company is the project-management layer for the whole fleet: the Mac mini
control plane (Mack), Rosie, Winnie, Airy, and Lenny, connected over Tailscale.

## Operating rules (summary; full text in the `fleet-conventions` skill)

- **Paperclip is where work is tracked.** Goals → projects → issues. Chat channels
  (Telegram, Discord, Buzz) are for conversation, not for task state.
- **One owner per issue.** Check out an issue before working it. An issue checked out
  by someone else is a hard claim.
- **Done means verified.** The executor never marks its own work done: review stages
  route it to a different agent, and approval stages to the board.
- **Report states separately:** implemented, pushed, reviewed, merged, deployed, accepted.
- **Ask first** for anything destructive, spending money, touching credentials,
  publishing, sending external messages, deploying, merging to a default branch, or
  changing access control. That means a Paperclip approval, not a silent default.
- **Never** force-push, push to a default branch directly, or commit secrets.
