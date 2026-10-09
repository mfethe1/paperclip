---
name: Daily fleet check
slug: daily-fleet-check
assignee: fleet-ops
project: fleet-operations
recurring: true
---

Run `scripts/fleet-check.sh` from the `mfethe1/paperclip` checkout on Mack and post
its table as a comment.

For every row that is not `ok`:
1. Search Fleet Operations for an open issue covering it; if one exists, comment with
   today's output.
2. Otherwise open a new issue with the failing check, the raw output, and a proposed fix.

Don't change any host from this routine. Diagnosis only.
