# Private Hermes connector admission candidate

Scope: read-only supplement to Paperclip's health-only adapter connection test. Not installed; no runtime, adapter, agent configuration or Buzz edits. No external Git remote or publishing authorization.

Call `admission.admit` only from the qualified Paperclip service origin with a separately resolved connector-only credential; never copy provider credentials or log tokens. Pin the intended host TLS endpoint in the caller. No CLI accepting a token argument is provided. Default TLS verification is mandatory; redirects and proxies are disabled. HTTP is permitted only for literal loopback test/local addresses. Acceptance requires missing/wrong credential401 and correct credential200 with a nonempty models-list response; does not call health, dispatch a run or expose model IDs/body in the receipt.

`python3 -m unittest discover -v` runs real socket HTTP fixtures and certificate-verified TLS fixtures using a generated test-only key. These are client contract tests, not fleet/service-origin acceptance. `python3 -m py_compile admission.py test_admission.py` is the syntax gate. Dedicated fixture credentials are synthetic test-only strings; no real keys used.

Deployment gates: independently review exact candidate; real service-origin authenticated positive/negative admission with endpoint binding and safe native credential resolution; exact correlated native adapter run and terminal receipt; reviewed work containment for anything beyond text-only qualification. All four hosts and portfolio capture must qualify before Buzz integration. Never equate this helper's pass with execution qualification.
