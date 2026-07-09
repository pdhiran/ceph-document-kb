"""Background auto-updater — pulls latest changes from git on startup
and periodically thereafter.

Runs ``git pull --ff-only origin <branch>`` in a daemon thread so the
server starts instantly with whatever is on disk, then:

- If only knowledge base files changed → hot-reload the search engine.
- If source code (.py) changed → ``sys.exit(0)`` so Cursor restarts
  the MCP server process with the updated code.

A second daemon thread wakes up every *update_interval_hours* (default 12)
to repeat the check.

Every failure path logs a warning and returns — the server is never
blocked or crashed by this.
"""

from __future__ import annotations

import logging
import os
import subprocess
import sys
import threading
import time
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ceph_doc_kb.server.mcp_server import CephDocMCPServer

logger = logging.getLogger(__name__)

_periodic_stop: threading.Event | None = None


def _find_repo_root(start: Path) -> Path | None:
    current = start.resolve()
    for parent in [current, *current.parents]:
        if (parent / ".git").exists():
            return parent
    return None


def _has_remote(repo_dir: Path) -> bool:
    try:
        result = subprocess.run(
            ["git", "remote"],
            cwd=repo_dir, capture_output=True, text=True, timeout=10,
        )
        return bool(result.stdout.strip())
    except Exception:
        return False


def _detect_default_branch(repo_dir: Path) -> str:
    try:
        result = subprocess.run(
            ["git", "symbolic-ref", "--short", "refs/remotes/origin/HEAD"],
            capture_output=True, text=True, cwd=str(repo_dir), timeout=10,
        )
        if result.returncode == 0:
            return result.stdout.strip().replace("origin/", "")
    except Exception:
        pass
    return "main"


def _get_head_sha(repo_dir: Path) -> str | None:
    try:
        result = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=repo_dir, capture_output=True, text=True, timeout=10,
        )
        if result.returncode == 0:
            return result.stdout.strip()
    except Exception:
        pass
    return None


def _changed_files(repo_dir: Path, old_sha: str, new_sha: str) -> list[str]:
    try:
        result = subprocess.run(
            ["git", "diff", "--name-only", old_sha, new_sha],
            cwd=repo_dir, capture_output=True, text=True, timeout=30,
        )
        if result.returncode == 0:
            return [f for f in result.stdout.strip().splitlines() if f]
    except Exception:
        pass
    return []


def _git_pull(repo_dir: Path) -> tuple[bool, str]:
    branch = _detect_default_branch(repo_dir)
    try:
        result = subprocess.run(
            ["git", "pull", "--ff-only", "origin", branch],
            cwd=repo_dir, capture_output=True, text=True, timeout=120,
        )
        output = result.stdout.strip()
        if result.returncode != 0:
            stderr = result.stderr.strip()
            return False, f"git pull failed: {stderr or output}"
        if "Already up to date" in output:
            return False, "Already up to date"
        return True, output
    except subprocess.TimeoutExpired:
        return False, "git pull timed out"
    except Exception as exc:
        return False, f"git pull error: {exc}"


def _has_code_changes(files: list[str]) -> bool:
    return any(f.endswith(".py") for f in files)


def _has_kb_changes(files: list[str]) -> bool:
    return any(f.startswith("knowledge/") for f in files)


def _do_update(
    doc_server: CephDocMCPServer,
    repo_root: Path,
    *,
    is_startup: bool = False,
) -> None:
    try:
        old_sha = _get_head_sha(repo_root)
        changed, message = _git_pull(repo_root)

        if not changed:
            if "failed" in message.lower() or "error" in message.lower() or "timed out" in message.lower():
                logger.warning("Auto-update: %s", message)
            else:
                logger.info("Repository is up to date")
            return

        new_sha = _get_head_sha(repo_root)
        files = _changed_files(repo_root, old_sha, new_sha) if old_sha and new_sha else []

        if _has_code_changes(files):
            logger.info("Code changes detected, restarting server")
            os._exit(0)

        if _has_kb_changes(files):
            logger.info("Knowledge base updated, hot-reloading")
            doc_server._router = None
            doc_server._load()

    except Exception as exc:
        logger.warning("Auto-update failed, continuing with existing data: %s", exc)


def _periodic_loop(
    doc_server: CephDocMCPServer,
    repo_root: Path,
    interval_seconds: float,
    stop_event: threading.Event,
) -> None:
    while not stop_event.wait(timeout=interval_seconds):
        _do_update(doc_server, repo_root)


def start_auto_update(
    doc_server: CephDocMCPServer,
    *,
    update_interval_hours: float = 1,
) -> None:
    """Pull latest changes from git now and schedule periodic re-checks.

    Safe to call unconditionally — silently skips if the repo directory
    has no git remote configured.
    """
    global _periodic_stop  # noqa: PLW0603

    if _periodic_stop is not None and not _periodic_stop.is_set():
        return

    repo_root = _find_repo_root(doc_server.kb_path)
    if repo_root is None or not _has_remote(repo_root):
        return

    thread = threading.Thread(
        target=_do_update,
        args=(doc_server, repo_root),
        kwargs={"is_startup": True},
        daemon=True,
        name="auto-update-startup",
    )
    thread.start()

    if update_interval_hours > 0:
        interval_seconds = update_interval_hours * 3600
        stop_event = threading.Event()
        _periodic_stop = stop_event
        periodic = threading.Thread(
            target=_periodic_loop,
            args=(doc_server, repo_root, interval_seconds, stop_event),
            daemon=True,
            name="auto-update-periodic",
        )
        periodic.start()


def stop_auto_update() -> None:
    global _periodic_stop  # noqa: PLW0603
    if _periodic_stop is not None:
        _periodic_stop.set()
        _periodic_stop = None
