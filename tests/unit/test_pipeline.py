from __future__ import annotations

import logging
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from core.downloader import DownloadError, VideoUnavailableError
from core.pipeline import Pipeline, PipelineResult
from core.transcriber import TranscriptionResult
from core.url_store import URLStore
from core.writer import Writer


URL_A = "https://www.youtube.com/watch?v=AAAAAAAAAAA"
URL_B = "https://www.youtube.com/watch?v=BBBBBBBBBBB"


def _make_pipeline(tmp_path: Path, pending_urls: list[str]) -> tuple[Pipeline, URLStore]:
    pending = tmp_path / "pending.txt"
    processed = tmp_path / "processed.txt"
    pending.write_text("\n".join(pending_urls) + "\n", encoding="utf-8")
    processed.touch()

    store = URLStore(pending_path=pending, processed_path=processed)
    downloader = MagicMock()
    transcriber = MagicMock()
    writer = MagicMock()

    mock_audio = tmp_path / "audio.m4a"
    mock_audio.touch()
    downloader.download.return_value = mock_audio
    transcriber.transcribe.return_value = TranscriptionResult(text="テスト", language="ja", segments=[])
    writer.write.return_value = tmp_path / "output.txt"

    pipeline = Pipeline(
        store=store,
        downloader=downloader,
        transcriber=transcriber,
        writer=writer,
        logger=logging.getLogger("test"),
    )
    return pipeline, store


# PP-01: 正常フロー → status == "success"
def test_pp01_success(tmp_path: Path) -> None:
    pipeline, _ = _make_pipeline(tmp_path, [URL_A])
    result = pipeline.run_once()
    assert result.status == "success"


# PP-02: VideoUnavailableError 発生 → スキップ、processed には追加されない
def test_pp02_video_unavailable_skips(tmp_path: Path) -> None:
    pipeline, store = _make_pipeline(tmp_path, [URL_A, URL_B])
    pipeline.downloader.download.side_effect = VideoUnavailableError("非公開")

    result = pipeline.run_once()

    assert result.status == "skip"
    processed = store.processed_path.read_text(encoding="utf-8")
    assert URL_A not in processed


# PP-03: DownloadError が3回連続 → リトライ3回後に status == "error"
def test_pp03_download_error_retries_and_fails(tmp_path: Path) -> None:
    pipeline, _ = _make_pipeline(tmp_path, [URL_A])
    pipeline.downloader.download.side_effect = DownloadError("ネットワーク障害")

    with patch("core.pipeline.time.sleep"):
        result = pipeline.run_once()

    assert result.status == "error"
    assert pipeline.downloader.download.call_count == 3


# PP-04: pending が空 → run_once() が即座に status == "empty" を返す
def test_pp04_empty_pending(tmp_path: Path) -> None:
    pipeline, _ = _make_pipeline(tmp_path, [])
    result = pipeline.run_once()
    assert result.status == "empty"
    assert result.url == ""


# PP-05: 処理中にクラッシュ → 一時ファイルが残存しない
def test_pp05_cleanup_on_transcription_error(tmp_path: Path) -> None:
    from core.transcriber import TranscriptionError

    pipeline, _ = _make_pipeline(tmp_path, [URL_A])
    mock_audio = tmp_path / "audio.m4a"
    mock_audio.touch()
    pipeline.downloader.download.return_value = mock_audio
    pipeline.transcriber.transcribe.side_effect = TranscriptionError("クラッシュ")

    result = pipeline.run_once()

    assert result.status == "error"
    pipeline.downloader.cleanup.assert_called_once_with(mock_audio)
