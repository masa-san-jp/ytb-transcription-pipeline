from __future__ import annotations

import sys
import types
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from core.downloader import VideoUnavailableError
from core.transcriber import TranscriptionResult


URL_A = "https://www.youtube.com/watch?v=AAAAAAAAAAA"
URL_B = "https://www.youtube.com/watch?v=BBBBBBBBBBB"
URL_C = "https://www.youtube.com/watch?v=CCCCCCCCCCC"

_MOCK_TRANSCRIPTION = {"text": "サンプル文字起こしテキスト", "language": "ja", "segments": []}


def _install_fake_mlx() -> None:
    fake_mlx = types.ModuleType("mlx_whisper")
    fake_mlx.transcribe = lambda *a, **kw: _MOCK_TRANSCRIPTION  # type: ignore[attr-defined]
    sys.modules.setdefault("mlx_whisper", fake_mlx)


def _make_pending(tmp_path: Path, urls: list[str]) -> tuple[Path, Path]:
    pending = tmp_path / "pending_urls.txt"
    processed = tmp_path / "processed_urls.txt"
    pending.write_text("\n".join(urls) + "\n", encoding="utf-8")
    processed.touch()
    return pending, processed


def _run_cli(argv: list[str]) -> int:
    from cli.run import main
    return main(argv)


@pytest.fixture(autouse=True)
def fake_mlx():
    _install_fake_mlx()
    yield


# P1-01: pending に3件、全て正常 → output/ に3ファイル生成
def test_p1_01_all_success(tmp_path: Path) -> None:
    pending, processed = _make_pending(tmp_path, [URL_A, URL_B, URL_C])
    output_dir = tmp_path / "output"
    audio_file = tmp_path / "audio.m4a"
    audio_file.touch()

    with (
        patch("core.downloader.subprocess.run") as mock_run,
        patch("core.downloader.uuid.uuid4") as mock_uuid,
        patch.object(Path, "exists", return_value=True),
    ):
        mock_run.return_value = MagicMock(returncode=0, stdout="", stderr="")
        mock_uuid.return_value.hex = "deadbeef"

        exit_code = _run_cli([
            "--pending", str(pending),
            "--processed", str(processed),
            "--output-dir", str(output_dir),
        ])

    assert exit_code == 0
    txt_files = list(output_dir.glob("*.txt"))
    assert len(txt_files) == 3


# P1-02: pending に3件、うち1件が非公開URL → 2件成功、1件スキップ、exitcode 0
def test_p1_02_one_unavailable(tmp_path: Path) -> None:
    pending, processed = _make_pending(tmp_path, [URL_A, URL_B, URL_C])
    output_dir = tmp_path / "output"

    call_count = 0

    def fake_download(url: str):
        nonlocal call_count
        call_count += 1
        if call_count == 2:
            raise VideoUnavailableError("非公開動画")
        audio = tmp_path / f"audio_{call_count}.m4a"
        audio.touch()
        return audio

    with (
        patch("core.downloader.Downloader.download", side_effect=fake_download),
        patch("core.downloader.Downloader.cleanup"),
    ):
        exit_code = _run_cli([
            "--pending", str(pending),
            "--processed", str(processed),
            "--output-dir", str(output_dir),
        ])

    assert exit_code == 0
    txt_files = list(output_dir.glob("*.txt"))
    assert len(txt_files) == 2


# P1-03: --dry-run 指定 → ファイル生成なし、件数のみ出力
def test_p1_03_dry_run(tmp_path: Path, capsys) -> None:
    pending, processed = _make_pending(tmp_path, [URL_A, URL_B])
    output_dir = tmp_path / "output"

    exit_code = _run_cli([
        "--pending", str(pending),
        "--processed", str(processed),
        "--output-dir", str(output_dir),
        "--dry-run",
    ])

    assert exit_code == 0
    assert not output_dir.exists()
    captured = capsys.readouterr()
    assert "2" in captured.out


# P1-04: output/ が存在しない → 自動作成されてから書き込まれる
def test_p1_04_output_dir_created(tmp_path: Path) -> None:
    pending, processed = _make_pending(tmp_path, [URL_A])
    output_dir = tmp_path / "nonexistent" / "output"
    assert not output_dir.exists()
    audio_file = tmp_path / "audio.m4a"
    audio_file.touch()

    with (
        patch("core.downloader.subprocess.run") as mock_run,
        patch("core.downloader.uuid.uuid4") as mock_uuid,
        patch.object(Path, "exists", return_value=True),
    ):
        mock_run.return_value = MagicMock(returncode=0, stdout="", stderr="")
        mock_uuid.return_value.hex = "deadbeef"

        exit_code = _run_cli([
            "--pending", str(pending),
            "--processed", str(processed),
            "--output-dir", str(output_dir),
        ])

    assert exit_code == 0
    assert output_dir.exists()
