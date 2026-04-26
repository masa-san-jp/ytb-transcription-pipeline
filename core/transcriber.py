from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class TranscriptionResult:
    text: str
    language: str
    segments: list[dict] = field(default_factory=list)


class TranscriptionError(Exception):
    """mlx-whisper が失敗"""


class Transcriber:
    MODEL_ID = "mlx-community/whisper-large-v3-mlx"

    def __init__(self, model_id: str = MODEL_ID) -> None:
        self.model_id = model_id

    def transcribe(self, audio_path: Path, language: str | None = None) -> TranscriptionResult:
        if not audio_path.exists():
            raise FileNotFoundError(f"音声ファイルが見つかりません: {audio_path}")

        try:
            import mlx_whisper  # type: ignore

            kwargs: dict = {"path_or_hf_repo": self.model_id}
            if language is not None:
                kwargs["language"] = language

            result = mlx_whisper.transcribe(str(audio_path), **kwargs)
        except ImportError as e:
            raise TranscriptionError(f"mlx_whisper がインストールされていません: {e}") from e
        except Exception as e:
            raise TranscriptionError(f"文字起こし失敗: {e}") from e

        return TranscriptionResult(
            text=result.get("text", ""),
            language=result.get("language", ""),
            segments=result.get("segments", []),
        )
