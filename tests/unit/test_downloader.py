from __future__ import annotations

import subprocess
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from core.downloader import Downloader, DownloadError, VideoUnavailableError


URL = "https://www.youtube.com/watch?v=TESTID"


def _make_completed_process(returncode: int, stdout: str = "", stderr: str = "") -> subprocess.CompletedProcess:
    return subprocess.CompletedProcess(args=[], returncode=returncode, stdout=stdout, stderr=stderr)


# DL-01: yt-dlp が成功を返す → 戻り値が Path オブジェクト
def test_dl01_success_returns_path(tmp_path: Path) -> None:
    downloader = Downloader()
    fake_path = tmp_path / "audio.m4a"
    fake_path.touch()

    with (
        patch("core.downloader.subprocess.run", return_value=_make_completed_process(0)) as mock_run,
        patch("core.downloader.uuid.uuid4") as mock_uuid,
    ):
        mock_uuid.return_value.hex = "deadbeef"
        with patch.object(Path, "exists", return_value=True):
            result = downloader.download(URL)

    assert isinstance(result, Path)
    mock_run.assert_called_once()


# DL-02: yt-dlp が "ERROR: Video unavailable" を返す → VideoUnavailableError
def test_dl02_video_unavailable_error(tmp_path: Path) -> None:
    downloader = Downloader()

    with patch("core.downloader.subprocess.run", return_value=_make_completed_process(1, stderr="ERROR: Video unavailable")):
        with pytest.raises(VideoUnavailableError):
            downloader.download(URL)


# DL-03: yt-dlp が "ERROR: Private video" を返す → VideoUnavailableError
def test_dl03_private_video_error() -> None:
    downloader = Downloader()

    with patch("core.downloader.subprocess.run", return_value=_make_completed_process(1, stderr="ERROR: Private video")):
        with pytest.raises(VideoUnavailableError):
            downloader.download(URL)


# DL-04: 成功後に cleanup() を呼ぶ → 一時ファイルが削除されている
def test_dl04_cleanup_deletes_file(tmp_path: Path) -> None:
    downloader = Downloader()
    tmp_file = tmp_path / "audio.m4a"
    tmp_file.touch()

    downloader.cleanup(tmp_file)

    assert not tmp_file.exists()


# DL-05: 例外発生後も一時ファイルが削除されている（リソースリーク無し）
def test_dl05_cleanup_on_exception() -> None:
    downloader = Downloader()

    with patch("core.downloader.subprocess.run", return_value=_make_completed_process(1, stderr="network error")):
        with patch("core.downloader.Path.unlink") as mock_unlink:
            with pytest.raises(DownloadError):
                downloader.download(URL)
            mock_unlink.assert_called()
