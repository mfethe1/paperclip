---
name: fleet-conventions
description: Rules every agent in Michael's fleet follows when taking, doing, handing off, and finishing Paperclip work, including ownership, evidence, approvals, git hygiene, and secrets. Use on every heartbeat before acting on an issue.
metadata:
  paperclip:
    tags:
      - fleet
      - governance
---

# Fleet conventions

These rules apply to every agent and every host. When an issue's instructions
conflict with this skill, follow the stricter rule and say so in the issue.

## 1. Where state lives

| Kind of state | Authority |
|---|---|
| Goals, projects, issues, assignments, approvals, budgets | **Paperclip** (this board) |
| Code | Git, on GitHub |
| Conversation and alerts | Telegram, Discord, Buzz channels: notify there, link back to the issue |
| Transport between hosts | Tailscale, SSH, peer-relay, NATS. These carry messages and are never a source of truth |

If you find work tracked somewhere else (a `TASK_QUEUE.md`, a Hermes Kanban card, a Buzz
task, a chat thread), don't start a parallel copy. Comment on the matching Paperclip
issue, or ask the Chief of Staff to import it.

## 2. Ownership

- Check out an issue before working it. An issue someone else has checked out is a
  hard claim. Do not touch it, even if it looks stale. Ask in the thread instead.
- One owner per issue. Split work into child issues instead of sharing one.
- Limit work in progress per project to 2 implementation issues and 3 verification issues.
- If you cannot continue, set `blocked` and state exactly what would unblock it.

## 3. Handoffs

End every run with a comment in this shape:

```
DID:  what you actually did (commands, files, links)
NEXT: the next concrete step and who owns it
NEED: decisions or access you're waiting on (or "nothing")
```

## 4. Done means verified

- Acceptance criteria come first. If the issue has none, write them and get them
  confirmed before you implement.
- Never mark your own work accepted. Review stages route to a different agent, and
  approval stages route to the board. Those stages exist only if the issue has an
  execution policy. If an issue you are about to finish has none, ask the Chief of
  Staff to set one rather than closing it yourself.
- Track these as separate states: **implemented → pushed → reviewed → merged →
  deployed → accepted**. Say which one you reached.
- Evidence is something a reviewer can rerun: the exact command and its output, a commit
  SHA, a PR link, or a screenshot of the running artifact at the expected commit.
  "Should work" is not evidence.
- If the same failure happens twice, stop and block. Don't loop.
- Allow at most 3 review rounds; after that, the Chief of Staff re-plans the issue.

## 5. Git

- Branch: `<agent>/<issue-identifier>-<short-slug>`.
- Commit: `[<agent>] <verb>: <what>`.
- Never force-push. Never push to `main`/`master` directly. Never rewrite someone
  else's branch. Never push branches marked private or brand-only to a public remote.
- Don't push automatically on another host's behalf. Unpushed work on a host belongs to that host's owner.

## 6. Ask first (Paperclip approval required)

Open an approval and wait for the board before you:

- delete data, branches, repos, or files outside your workspace
- spend money, change budgets, or start paid compute (GPU rentals, cloud resources)
- create, rotate, read out, or move credentials
- publish anything, or send email or messages to anyone outside the fleet
- deploy, merge to a default branch, or change production
- change access control, Tailscale configuration, or launchd/systemd units on a host
- turn on anything that runs on a schedule

An approval covers exactly what it names. Silence is never approval.

## 7. Secrets and identifiers

- Never put secret values, tokens, private keys, tailnet hostnames, tailnet IPs, or
  home-directory paths in issues, comments, commits, or package files. Refer to
  secrets by name (`GH_TOKEN`), and to hosts by alias (Mack, Rosie, Winnie, Airy, Lenny).
- Use Paperclip secrets for credentials agents need; never paste them into instructions.
- Claude Code authenticates with OAuth on each host; don't copy session databases or
  refresh tokens between hosts.

## 8. Hosts

| Alias | Role | Notes |
|---|---|---|
| Mack | Control plane and durable execution | Always on. After a cold boot it waits for a manual FileVault unlock. |
| Rosie | OpenClaw integrations, home automation | Owns the OpenClaw gateway. |
| Winnie | GPU inference (Ollama), Windows tasks, bulk storage | SSH lands in PowerShell 5.1 (`&&` fails; scp/rsync unreliable). Small C: drive. |
| Airy | Operator laptop | Not durable. Never schedule work that depends on it being awake. |
| Lenny | Linux spare | Read-only probes only unless an issue says otherwise. |

A heartbeat or cached status file is not proof a host is alive. Probe it.
