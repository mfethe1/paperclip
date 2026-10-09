# REJECTED — original connector admission baseline

This directory preserves the **rejected** original admission candidate
(source commit `8d20d5fc8af7275fdc969f04b05c1423e4cc9619`), frozen
read-only for provenance and review contrast.

An independent security review of this exact code reproduced:

1. **Secret-bearing HTTP exception propagation** — error paths could
   carry credential material outward through raw exception contexts.
2. **URL route confusion** — URL handling did not enforce the route
   contract the revised module now pins.

**Do not use this code.** The reviewed, accepted replacement is in
`../connector-admission/` (source commit
`4e789b8a01efa605dcd203380b4d64878bf2699c`), which regenerated the
module under the corrected URL/exception contract and passed the full
real HTTP/TLS suite plus independent reproduction.

The shipped `test_admission.py` here is byte-identical to the one in
`../connector-admission/`; it is retained so the rejection delta is
auditable.
