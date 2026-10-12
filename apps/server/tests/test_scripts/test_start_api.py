"""API startup bootstrap tests."""

import importlib
import os
from unittest import mock


with mock.patch.dict(os.environ):
    startup = importlib.import_module("scripts.start_api")


def test_default_start_execs_uvicorn_with_existing_production_timeouts():
    exec_calls: list[tuple[str, list[str]]] = []

    startup.main(
        environment={"PORT": "9000", "WEB_CONCURRENCY": "3"},
        execvp=lambda executable, command: exec_calls.append((executable, list(command))),
    )

    assert exec_calls == [
        (
            "uvicorn",
            [
                "uvicorn",
                "main:app",
                "--host",
                "0.0.0.0",
                "--port",
                "9000",
                "--workers",
                "3",
                "--timeout-keep-alive",
                "300",
                "--timeout-worker-healthcheck",
                "600",
                "--timeout-graceful-shutdown",
                "295",
            ],
        )
    ]


def test_default_port_and_worker_count_are_stable():
    assert startup._api_command({})[5:9] == ["8000", "--workers", "1", "--timeout-keep-alive"]
