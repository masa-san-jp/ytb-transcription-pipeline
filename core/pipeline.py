from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal

from core.downloader import Downloader, DownloadError, VideoUnavailableError
from core.transcriber import Transcriber, TranscriptionError
from core.url_store import URLStore
from core.writer import Writer, WriteError

_RETRY_MAX = 3
_RETRY_BASE_SEC = 2.0

Status = Literal["success", "skip", "error", "empty"]


@dataclass
class PipelineResult:
    url: str
    status: Status
    output_path: Path | None = None
    error: str | None = None


class Pipeline:
    def __init__(
        self,
        store: URLStore,
        downloader: Downloader,
        transcriber: Transcriber,
        writer: Writer,
        logger: logging.Logger | None = None,
    ) -> None:
        self.store = store
        self.downloader = downloader
        self.transcriber = transcriber
        self.writer = writer
        self.logger = logger or logging.getLogger(__name__)

    def run_once(self) -> PipelineResult:
        url = self.store.pop_next()
        if url is None:
            return PipelineResult(url="", status="empty")

        self.logger.info("処理開始: %s", url)

        audio_path = None
        try:
            audio_path = self._download_with_retry(url)
        except VideoUnavailableError as e:
            self.logger.warning("スキップ (動画利用不可): %s — %s", url, e)
            return PipelineResult(url=url, status="skip", error=str(e))
        except DownloadError as e:
            self.logger.error("エラー (ダウンロード失敗): %s — %s", url, e)
            return PipelineResult(url=url, status="error", error=str(e))

        try:
            transcription = self.transcriber.transcribe(audio_path)
            video_id = _extract_video_id(url)
            title = video_id
            output_path = self.writer.write(transcription, title, video_id)
            self.store.mark_done(url)
            self.logger.info("完了: %s → %s", url, output_path)
            return PipelineResult(url=url, status="success", output_path=output_path)
        except (TranscriptionError, WriteError) as e:
            self.logger.error("エラー: %s — %s", url, e)
            return PipelineResult(url=url, status="error", error=str(e))
        finally:
            if audio_path is not None:
                self.downloader.cleanup(audio_path)

    def run_all(self) -> list[PipelineResult]:
        results: list[PipelineResult] = []
        while True:
            result = self.run_once()
            if result.status == "empty":
                break
            results.append(result)
        return results

    def _download_with_retry(self, url: str) -> Path:
        last_error: DownloadError | None = None
        for attempt in range(_RETRY_MAX):
            try:
                return self.downloader.download(url)
            except VideoUnavailableError:
                raise
            except DownloadError as e:
                last_error = e
                if attempt < _RETRY_MAX - 1:
                    wait = _RETRY_BASE_SEC * (2 ** attempt)
                    self.logger.warning("リトライ %d/%d: %s (%.1fs後)", attempt + 1, _RETRY_MAX, url, wait)
                    time.sleep(wait)
        raise last_error  # type: ignore[misc]


def _extract_video_id(url: str) -> str:
    import re
    match = re.search(r"(?:v=|youtu\.be/)([A-Za-z0-9_-]{11})", url)
    return match.group(1) if match else "unknown"
