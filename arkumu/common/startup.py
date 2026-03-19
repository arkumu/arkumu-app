import os
from typing import Sequence


_SKIP_STARTUP_COMMANDS = frozenset(
    {
        "check",
        "collectstatic",
        "compilemessages",
        "dbshell",
        "makemessages",
        "makemigrations",
        "migrate",
        "run_huey",
        "shell",
        "test",
    }
)


def should_skip_startup_warmup(argv: Sequence[str]) -> bool:
    """Return True when startup warmups should be skipped for this process."""
    if os.environ.get("ARKUMU_SKIP_STARTUP_WARMUP", "").strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
    }:
        return True

    if os.environ.get("PYTEST_CURRENT_TEST"):
        return True

    if len(argv) < 2:
        return False

    if any("pytest" in arg for arg in argv[:2]):
        return True

    return argv[1] in _SKIP_STARTUP_COMMANDS
