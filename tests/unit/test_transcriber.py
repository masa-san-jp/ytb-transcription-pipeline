from __future__ import annotations

import sys
import types
from pathlib import Path

import pytest

from core.transcriber import TranscriptionResult, Transcriber


_MOCK_RESULT = {
    "text": "こんにちは世界",
    "language": "ja",
    "segments": [{"start": 0.0, "end": 1.5, "text": "こんにちは世界"}],
}


def _fake_mlx(transcribe_fn=None):
    mod = types.ModuleType("mlx_whisper")
    mod.transcribe = transcribe_fn or (lambda *a, **kw: _MOCK_RESULT)  # type: ignore[attr-defined]
    return mod


# TR-01: モックで正常な結果を返す → TranscriptionResult.text が空でない
def test_tr01_success_returns_nonempty_text(tmp_path: Path) -> None:
    audio = tmp_path / "audio.m4a"
    audio.touch()
    transcriber = Transcriber()

    sys.modules["mlx_whisper"] = _fake_mlx()
    try:
        result = transcriber.transcribe(audio)
        assert isinstance(result, TranscriptionResult)
        assert result.text != ""
    finally:
        sys.modules.pop("mlx_whisper", None)


# TR-02: 音声ファイルが存在しない → FileNotFoundError
def test_tr02_file_not_found(tmp_path: Path) -> None:
    audio = tmp_path / "nonexistent.m4a"
    transcriber = Transcriber()

    with pytest.raises(FileNotFoundError):
        transcriber.transcribe(audio)


# TR-03: language="ja" を指定 → mlx-whisper に language="ja" が渡される
def test_tr03_language_passed_to_mlx(tmp_path: Path) -> None:
    audio = tmp_path / "audio.m4a"
    audio.touch()
    transcriber = Transcriber()

    calls: list[dict] = []

    def capturing_transcribe(*args, **kwargs):
        calls.append(kwargs)
        return _MOCK_RESULT

    sys.modules["mlx_whisper"] = _fake_mlx(capturing_transcribe)
    try:
        transcriber.transcribe(audio, language="ja")
        assert calls[0].get("language") == "ja"
    finally:
        sys.modules.pop("mlx_whisper", None)
