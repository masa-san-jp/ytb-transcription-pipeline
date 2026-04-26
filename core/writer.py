from __future__ import annotations

import re
from pathlib import Path

from core.transcriber import TranscriptionResult


class WriteError(Exception):
    """出力先への書き込み失敗"""


class Writer:
    def __init__(self, output_dir: Path) -> None:
        self.output_dir = output_dir

    def write(self, result: TranscriptionResult, title: str, video_id: str) -> Path:
        try:
            self.output_dir.mkdir(parents=True, exist_ok=True)
            safe_title = _sanitize_filename(title)
            filename = f"{safe_title}_{video_id}.txt"
            output_path = self.output_dir / filename
            output_path.write_text(result.text, encoding="utf-8")
            return output_path
        except OSError as e:
            raise WriteError(f"ファイル書き込み失敗: {e}") from e


def _sanitize_filename(name: str) -> str:
    return re.sub(r'[\\/:*?"<>|\x00-\x1f]', "_", name).strip("_").strip()
