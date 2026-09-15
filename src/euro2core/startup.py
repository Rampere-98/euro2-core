"""Make `euro2 serve` survive a machine reboot on its own: wait for PostgreSQL and, on a
Windows desktop where the database runs in Docker Desktop, start Docker and the compose
stack when they are not up yet. Nothing here is needed on a server (compose orders the
services); it only kicks in when the database is unreachable."""

import asyncio
import logging
import os
import shutil
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

log = logging.getLogger(__name__)

WAIT_SECONDS = 15 * 60
DOCKER_DESKTOP = (
    Path(os.environ.get("LOCALAPPDATA", "")) / "Programs/DockerDesktop/Docker Desktop.exe"
)
DOCKER_CLI = DOCKER_DESKTOP.parent / "resources/bin/docker.exe"
PROJECT_ROOT = Path(__file__).resolve().parents[2]


async def _reachable(url: str) -> bool:
    engine = create_async_engine(url, connect_args={"timeout": 5})
    try:
        async with engine.connect() as conn:
            await conn.execute(text("select 1"))
        return True
    except Exception:
        return False
    finally:
        await engine.dispose()


def _docker() -> str | None:
    return shutil.which("docker") or (str(DOCKER_CLI) if DOCKER_CLI.exists() else None)


def _docker_engine_up(docker: str) -> bool:
    try:
        return subprocess.run([docker, "info"], capture_output=True, timeout=20).returncode == 0
    except Exception:
        return False


def _start_local_stack() -> None:
    """Windows desktop only: launch Docker Desktop if needed, then `docker compose up -d`."""
    if sys.platform != "win32" or not (PROJECT_ROOT / "docker-compose.yml").exists():
        return
    docker = _docker()
    if docker is None:
        return
    if not _docker_engine_up(docker):
        if DOCKER_DESKTOP.exists():
            log.info("Docker Desktop is not running; starting it")
            subprocess.Popen([str(DOCKER_DESKTOP)], creationflags=subprocess.DETACHED_PROCESS)
        deadline = time.monotonic() + 5 * 60
        while time.monotonic() < deadline and not _docker_engine_up(docker):
            time.sleep(5)
    if _docker_engine_up(docker):
        log.info("starting the database container (docker compose up -d)")
        subprocess.run([docker, "compose", "up", "-d"], cwd=PROJECT_ROOT, capture_output=True)


def wait_for_database(url: str, *, timeout: float = WAIT_SECONDS) -> bool:
    """Block until PostgreSQL answers (starting the local Docker stack once if it is down)."""
    if asyncio.run(_reachable(url)):
        return True
    log.warning("database unreachable; waiting up to %d minutes", int(timeout // 60))
    _start_local_stack()
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if asyncio.run(_reachable(url)):
            log.info("database is up")
            return True
        time.sleep(5)
    return False


def already_running(host: str, port: int) -> bool:
    """True when something already answers /health on this address (a second `serve`)."""
    try:
        with urllib.request.urlopen(f"http://{host}:{port}/health", timeout=2) as r:
            return r.status == 200
    except Exception:
        return False
