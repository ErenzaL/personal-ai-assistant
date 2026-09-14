"""Run the API for the desktop app. Also the entry point of the packaged backend.

The app starts this instead of calling uvicorn directly so that the backend
never outlives the app: a thread watches the parent process and, if it goes
away for any reason (quit, crash, force quit), asks uvicorn to shut down
gracefully. Binds to localhost only. `--quiet` keeps the production log to
warnings and errors.
"""

from __future__ import annotations

import argparse
import os
import signal
import threading
import time

# How often to check on the parent. One cheap syscall; no CPU worth noticing.
PARENT_CHECK_SECONDS = 2.0


def _alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def _watch_parent(app_pid: int) -> None:
    """Shut down when the app is gone. The app passes its own pid because in
    the packaged build this process is a grandchild (PyInstaller starts a
    small bootloader first), so the immediate parent is not the app."""
    while True:
        time.sleep(PARENT_CHECK_SECONDS)
        if not _alive(app_pid):
            # Same signal the app sends on a normal quit: uvicorn finishes
            # in-flight requests and closes the database cleanly.
            os.kill(os.getpid(), signal.SIGTERM)
            return


def main() -> None:
    parser = argparse.ArgumentParser(description="Dully's local backend")
    parser.add_argument("--port", type=int, default=8000)
    parser.add_argument("--quiet", action="store_true", help="log warnings and errors only")
    parser.add_argument("--parent-pid", type=int, default=0, help="exit when this process ends")
    args = parser.parse_args()
    if not 1024 <= args.port <= 65535:
        parser.error("--port must be between 1024 and 65535")

    if args.quiet:
        os.environ.setdefault("DULLY_LOG_LEVEL", "WARNING")

    # Imported here, after the log level is known. Importing the app object
    # (rather than naming it as a string) also lets the packager find it.
    import uvicorn

    from app.main import app as api

    watched = args.parent_pid or os.getppid()
    threading.Thread(target=_watch_parent, args=(watched,), daemon=True).start()
    uvicorn.run(
        api,
        host="127.0.0.1",
        port=args.port,
        log_level="warning" if args.quiet else "info",
        access_log=not args.quiet,
    )


if __name__ == "__main__":
    main()
