---
name: Daily fleet check
slug: daily-fleet-check
assignee: fleet-ops
project: fleet-operations
recurring: true
---

From the `mfethe1/paperclip` checkout on the board host, run:

1. `scripts/fleet-check.sh`: hosts, the board, backups, gateways.
2. `scripts/diagnose.sh`: agent run failures grouped by cause, with the fix for each.

Post both reports as one comment. For every row that is not `ok`, and every FAIL or
CRITICAL group:
1. Search Fleet Operations for an open issue covering it. If one exists, comment
   with today's output.
2. Otherwise open a new issue with the failing check, the raw output, and the fix
   the report names.

Don't change any host from this routine. Diagnosis only.
