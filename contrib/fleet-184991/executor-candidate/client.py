"""Fixed Paperclip process entrypoint. Always closed until a separate reviewed backend exists."""

import sys

from executor import canonical, main

if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as error:  # noqa: BLE001 -- adapter boundary must fail closed without secret-bearing tracebacks
        # No task text, credentials, stdout streams or traceback in adapter logs.
        print(
            canonical(
                {"error_type": type(error).__name__, "execution_enabled": False}
            ).decode(),
            file=sys.stderr,
        )
        raise SystemExit(2)
