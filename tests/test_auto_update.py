"""Mock workflows: git-pull hot-reload, .py → process exit, .reload_trigger, update_index.sh."""

from __future__ import annotations

import os
import subprocess
import threading
import time
from datetime import date, timedelta
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from ceph_doc_kb.server.auto_update import (
    _do_update,
    _find_repo_root,
    _has_kb_changes,
    _trigger_loop,
    start_auto_update,
    stop_auto_update,
)

REPO = Path(__file__).resolve().parents[1]


def _copy_update_script(tmp_path: Path) -> Path:
    script = tmp_path / "update_index.sh"
    script.write_text((REPO / "update_index.sh").read_text())
    script.chmod(0o755)
    return script


def _skip_env() -> dict[str, str]:
    return {**os.environ, "SKIP_UPSTREAM": "1", "SKIP_IBM": "1"}


@pytest.fixture(autouse=True)
def _cleanup_auto_update():
    yield
    stop_auto_update()


class TestReloadFromDisk:
    def test_rediscovers_ibm_additional_kb(self, tmp_path):
        import json

        from ceph_doc_kb.server.mcp_server import CephDocMCPServer

        def meta(ceph: str) -> str:
            return json.dumps({
                "version": "1",
                "ceph_version": ceph,
                "embedding_model": "x",
                "embedding_dimensions": 8,
                "total_chunks": 1,
            })

        primary = tmp_path / "knowledge" / "doc-20.2.1"
        ibm = tmp_path / "knowledge" / "doc-ibm-9.1"
        primary.mkdir(parents=True)
        ibm.mkdir(parents=True)
        (primary / "metadata.json").write_text(meta("20.2.1"))
        (ibm / "metadata.json").write_text(meta("ibm-9.1"))
        (ibm / "command_xref.json").write_text(json.dumps({"ceph osd ls": [{"page": "x"}]}))

        srv = CephDocMCPServer(primary, {})
        srv._load()
        assert srv.metadata is not None
        assert srv.metadata.ceph_version == "20.2.1"
        assert srv._additional_metadata == []

        with patch("ceph_doc_kb.search.router.SearchRouter"):
            srv.reload_from_disk()

        assert len(srv._additional_metadata) == 1
        assert srv._additional_metadata[0].ceph_version == "ibm-9.1"
        assert "ceph osd ls" in srv.command_xref


class TestHelpers:
    def test_finds_git_dir(self, tmp_path):
        (tmp_path / ".git").mkdir()
        nested = tmp_path / "knowledge" / "doc-20.2.1"
        nested.mkdir(parents=True)
        assert _find_repo_root(nested) == tmp_path

    def test_kb_change_detection(self):
        assert _has_kb_changes(["knowledge/doc-20.2.1/metadata.json"])
        assert not _has_kb_changes(["README.md"])


class TestDoUpdate:
    def test_knowledge_pull_hot_reloads(self, tmp_path):
        doc_server = MagicMock()
        with (
            patch("ceph_doc_kb.server.auto_update._git_pull", return_value=(True, "Updated")),
            patch("ceph_doc_kb.server.auto_update._get_head_sha", side_effect=["aaa", "bbb"]),
            patch(
                "ceph_doc_kb.server.auto_update._changed_files",
                return_value=["knowledge/doc-ibm-9.1/metadata.json"],
            ),
            patch("ceph_doc_kb.server.auto_update.os._exit") as mock_exit,
        ):
            _do_update(doc_server, tmp_path)
        doc_server.reload_from_disk.assert_called_once()
        mock_exit.assert_not_called()

    def test_empty_file_list_still_reloads(self, tmp_path):
        doc_server = MagicMock()
        with (
            patch("ceph_doc_kb.server.auto_update._git_pull", return_value=(True, "Updated")),
            patch("ceph_doc_kb.server.auto_update._get_head_sha", side_effect=["aaa", "bbb"]),
            patch("ceph_doc_kb.server.auto_update._changed_files", return_value=[]),
            patch("ceph_doc_kb.server.auto_update.os._exit") as mock_exit,
        ):
            _do_update(doc_server, tmp_path)
        doc_server.reload_from_disk.assert_called_once()
        mock_exit.assert_not_called()

    def test_python_change_exits_process(self, tmp_path):
        doc_server = MagicMock()
        with (
            patch("ceph_doc_kb.server.auto_update._git_pull", return_value=(True, "Updated")),
            patch("ceph_doc_kb.server.auto_update._get_head_sha", side_effect=["aaa", "bbb"]),
            patch(
                "ceph_doc_kb.server.auto_update._changed_files",
                return_value=["src/ceph_doc_kb/server/mcp_server.py"],
            ),
            patch("ceph_doc_kb.server.auto_update.os._exit") as mock_exit,
        ):
            _do_update(doc_server, tmp_path)
        mock_exit.assert_called_once_with(0)
        doc_server.reload_from_disk.assert_not_called()

    def test_already_up_to_date_skips_reload(self, tmp_path):
        doc_server = MagicMock()
        with patch(
            "ceph_doc_kb.server.auto_update._git_pull",
            return_value=(False, "Already up to date"),
        ):
            _do_update(doc_server, tmp_path)
        doc_server.reload_from_disk.assert_not_called()


class TestTriggerLoop:
    def test_touch_trigger_reloads_without_git(self, tmp_path):
        doc_server = MagicMock()
        stop = threading.Event()
        with patch("ceph_doc_kb.server.auto_update.TRIGGER_POLL_SECONDS", 0.05):
            t = threading.Thread(
                target=_trigger_loop,
                args=(doc_server, tmp_path, stop),
                daemon=True,
            )
            t.start()
            time.sleep(0.08)
            (tmp_path / ".reload_trigger").write_text("1")
            deadline = time.time() + 2.0
            while time.time() < deadline and not doc_server.reload_from_disk.called:
                time.sleep(0.05)
            stop.set()
            t.join(timeout=1)
        doc_server.reload_from_disk.assert_called()


class TestStartAutoUpdate:
    def test_no_git_still_watches_trigger(self, tmp_path):
        knowledge = tmp_path / "knowledge" / "doc-20.2.1"
        knowledge.mkdir(parents=True)
        doc_server = MagicMock()
        doc_server.kb_path = knowledge
        start_auto_update(doc_server, update_interval_hours=0)
        time.sleep(0.05)
        names = [t.name for t in threading.enumerate()]
        assert "kb-reload-trigger" in names
        assert "auto-update-startup" not in names
        assert "auto-update-periodic" not in names

    def test_no_remote_still_starts_trigger(self, tmp_path):
        (tmp_path / ".git").mkdir()
        doc_server = MagicMock()
        doc_server.kb_path = tmp_path
        with patch("ceph_doc_kb.server.auto_update._has_remote", return_value=False):
            start_auto_update(doc_server, update_interval_hours=0)
        time.sleep(0.05)
        names = [t.name for t in threading.enumerate()]
        assert "kb-reload-trigger" in names

    def test_remote_starts_startup_and_trigger(self, tmp_path):
        (tmp_path / ".git").mkdir()
        doc_server = MagicMock()
        doc_server.kb_path = tmp_path
        with (
            patch("ceph_doc_kb.server.auto_update._has_remote", return_value=True),
            patch("ceph_doc_kb.server.auto_update._do_update"),
            patch(
                "ceph_doc_kb.server.auto_update.threading.Thread",
                wraps=threading.Thread,
            ) as mock_thread,
        ):
            start_auto_update(doc_server, update_interval_hours=0)
        names = [c.kwargs.get("name") for c in mock_thread.call_args_list]
        assert "auto-update-startup" in names
        assert "auto-update-periodic" not in names
        assert "kb-reload-trigger" in names


class TestNoAutoUpdateKillsBoth:
    def _run_main(self, argv: list[str]):
        from ceph_doc_kb.server.mcp_server import main

        def _close_coro(coro):
            coro.close()

        with (
            patch("ceph_doc_kb.server.mcp_server._silence_stderr_logging"),
            patch(
                "ceph_doc_kb.server.mcp_server.create_server",
                return_value=(MagicMock(), MagicMock()),
            ),
            patch("ceph_doc_kb.server.auto_update.start_auto_update") as mock_start,
            patch("asyncio.run", side_effect=_close_coro),
        ):
            main(argv)
        return mock_start

    def test_flag_skips_start_auto_update(self):
        mock_start = self._run_main(["--no-auto-update"])
        mock_start.assert_not_called()

    def test_default_starts_auto_update(self):
        mock_start = self._run_main([])
        mock_start.assert_called_once()

    def test_source_start_is_only_behind_auto_update_flag(self):
        text = (REPO / "src/ceph_doc_kb/server/mcp_server.py").read_text()
        before, after = text.split("if args.auto_update:", 1)
        assert "start_auto_update(" not in before
        guarded = after.split("if args.transport")[0]
        assert "start_auto_update(" in guarded


class TestUpdateIndexScript:
    def test_script_touches_reload_trigger(self):
        text = (REPO / "update_index.sh").read_text()
        assert "touch .reload_trigger" in text
        assert "index_docs.py" in text
        assert "index_ibm_docs.py" in text

    def test_reset_clears_tracker(self, tmp_path):
        script = _copy_update_script(tmp_path)
        (tmp_path / ".last_index_update").write_text("2026-01-01\n")
        subprocess.run([str(script), "--reset"], cwd=tmp_path, check=True)
        assert not (tmp_path / ".last_index_update").exists()

    def test_updating_md_documents_canonical_command(self):
        text = (REPO / "UPDATING.md").read_text()
        assert "./update_index.sh" in text
        assert "reload_from_disk" in text
        assert "Without `--cache-dir`" in text
        assert "--no-auto-update" in text
        assert '"cwd": "/path/to/ceph-document-kb"' in text

    def test_touch_is_after_skip_blocks(self):
        text = (REPO / "update_index.sh").read_text()
        assert text.index("touch .reload_trigger") > text.index("SKIP_IBM")
        assert text.index("touch .reload_trigger") > text.index("SKIP_UPSTREAM")

    def test_skip_upstream_and_ibm_still_touches_trigger(self, tmp_path):
        script = _copy_update_script(tmp_path)
        subprocess.run([str(script)], cwd=tmp_path, check=True, env=_skip_env())
        assert (tmp_path / ".reload_trigger").exists()

    def test_invalid_date_exits_before_tracker_or_trigger(self, tmp_path):
        script = _copy_update_script(tmp_path)
        (tmp_path / ".last_index_update").write_text("2026-01-01\n")
        r = subprocess.run(
            [str(script), "not-a-date"],
            cwd=tmp_path, capture_output=True, text=True, env=_skip_env(),
        )
        assert r.returncode == 1
        assert "invalid date" in r.stderr
        assert "YYYY-MM-DD" in r.stderr
        assert (tmp_path / ".last_index_update").read_text() == "2026-01-01\n"
        assert not (tmp_path / ".reload_trigger").exists()

    def test_invalid_calendar_iso_is_rejected(self, tmp_path):
        script = _copy_update_script(tmp_path)
        r = subprocess.run(
            [str(script), "2026-13-01"],
            cwd=tmp_path, capture_output=True, text=True, env=_skip_env(),
        )
        assert r.returncode == 1
        assert "invalid date" in r.stderr
        assert "2026-13-01" in r.stderr
        assert not (tmp_path / ".last_index_update").exists()
        assert not (tmp_path / ".reload_trigger").exists()

    def test_last_file_is_used_as_since(self, tmp_path):
        script = _copy_update_script(tmp_path)
        (tmp_path / ".last_index_update").write_text("2026-01-15\n")
        r = subprocess.run(
            [str(script)], cwd=tmp_path, capture_output=True, text=True, env=_skip_env(),
        )
        assert r.returncode == 0
        assert "Last successful run: 2026-01-15" in r.stdout
        assert "Delta since: 2026-01-15" in r.stdout

    def test_last_file_invalid_iso_is_rejected(self, tmp_path):
        script = _copy_update_script(tmp_path)
        (tmp_path / ".last_index_update").write_text("2026-13-01\n")
        r = subprocess.run(
            [str(script)], cwd=tmp_path, capture_output=True, text=True, env=_skip_env(),
        )
        assert r.returncode == 1
        assert "invalid date" in r.stderr
        assert (tmp_path / ".last_index_update").read_text() == "2026-13-01\n"
        assert not (tmp_path / ".reload_trigger").exists()

    def test_successful_run_writes_yesterday_not_since(self, tmp_path):
        script = _copy_update_script(tmp_path)
        (tmp_path / ".last_index_update").write_text("2026-01-15\n")
        r = subprocess.run(
            [str(script)], cwd=tmp_path, capture_output=True, text=True, env=_skip_env(),
        )
        assert r.returncode == 0
        yesterday = (date.today() - timedelta(days=1)).isoformat()
        assert (tmp_path / ".last_index_update").read_text().strip() == yesterday
        assert yesterday != "2026-01-15"
        assert (tmp_path / ".reload_trigger").exists()

    def test_last_index_update_write_is_yesterday_in_source(self):
        text = (REPO / "update_index.sh").read_text()
        assert 'date -v-1d +%Y-%m-%d > "$LAST_RUN_FILE"' in text
        assert text.index("touch .reload_trigger") < text.index('> "$LAST_RUN_FILE"')
