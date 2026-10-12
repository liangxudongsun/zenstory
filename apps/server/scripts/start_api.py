#!/usr/bin/env python3
"""Replace the API bootstrap with Uvicorn without blocking startup maintenance."""
from __future__ import annotations

import os
from collections.abc import Callable, Mapping, Sequence


def _api_command(environment: Mapping[str, str]) -> list[str]:
    return [
        "uvicorn",
        "main:app",
        "--host",
        "0.0.0.0",
        "--port",
        environment.get("PORT", "8000"),
        "--workers",
        environment.get("WEB_CONCURRENCY", "1"),
        "--timeout-keep-alive",
        "300",
        "--timeout-worker-healthcheck",
        "600",
        "--timeout-graceful-shutdown",
        "295",
    ]



def main(
    _argv: Sequence[str] | None = None,
    *,
    environment: Mapping[str, str] | None = None,
    execvp: Callable[[str, Sequence[str]], object] = os.execvp,
) -> int:
    command = _api_command(os.environ if environment is None else environment)
    execvp(command[0], command)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
