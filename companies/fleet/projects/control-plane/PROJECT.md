---
name: Control Plane
slug: control-plane
description: This Paperclip deployment, covering its install, upgrades, backups, company package, and the migration of existing fleet work onto the board.
owner: fleet-ops
---

The source of truth for how the control plane is deployed is the `mfethe1/paperclip`
repository: scripts, runbooks, and this company package. Changes to the deployment go
through pull requests to that repo; the board's own configuration is exported back
into `companies/fleet` with `scripts/export-company.sh`.
