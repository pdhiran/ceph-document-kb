"""Mock workflows: git-pull hot-reload, .py → process exit, .reload_trigger, update_index.sh."""

from __future__ import annotations

import subprocess
import threading
import time
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
    def test_no_remote_still_starts_trigger(self, tmp_path):
        (tmp_path / ".git").mkdir()
        doc_server = MagicMock()
        doc_server.kb_path = tmp_path
        with patch("ceph_doc_kb.server.auto_update._has_remote", return_value=False):
            start_auto_update(doc_server, update_interval_hours=0)
        time.sleep(0.05)
        names = [t.name for t in threading.enumerate()]
        assert "kb-reload-trigger" in names


class TestUpdateIndexScript:
    def test_script_touches_reload_trigger(self):
        text = (REPO / "update_index.sh").read_text()
        assert "touch .reload_trigger" in text
        assert "index_docs.py" in text
        assert "index_ibm_docs.py" in text

    def test_reset_clears_tracker(self, tmp_path):
        script = tmp_path / "update_index.sh"
        script.write_text((REPO / "update_index.sh").read_text())
        script.chmod(0o755)
        (tmp_path / ".last_index_update").write_text("2026-01-01\n")
        subprocess.run([str(script), "--reset"], cwd=tmp_path, check=True)
        assert not (tmp_path / ".last_index_update").exists()

    def test_updating_md_documents_canonical_command(self):
        text = (REPO / "UPDATING.md").read_text()
        assert "./update_index.sh" in text
        assert "reload_from_disk" in text
