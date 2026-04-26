from __future__ import annotations

import sys
import types
from pathlib import Path
from unittest.mock import MagicMock, call, patch

import pytest

from core.transcriber import TranscriptionResult

URL_A = "https://www.youtube.com/watch?v=AAAAAAAAAAA"
URL_B = "https://www.youtube.com/watch?v=BBBBBBBBBBB"

_MOCK_TRANSCRIPTION = {"text": "テスト文字起こし", "language": "ja", "segments": []}


@pytest.fixture(autouse=True)
def fake_mlx():
    fake = types.ModuleType("mlx_whisper")
    fake.transcribe = lambda *a, **kw: _MOCK_TRANSCRIPTION  # type: ignore[attr-defined]
    sys.modules["mlx_whisper"] = fake
    yield
    sys.modules.pop("mlx_whisper", None)


def _write_pending(path: Path, urls: list[str]) -> None:
    path.write_text("\n".join(urls) + "\n", encoding="utf-8")


# P3-01: run_and_commit.py を実行 → git pull が先に呼ばれること
def test_p3_01_git_pull_called_first(tmp_path: Path) -> None:
    from runner.run_and_commit import main

    pending = tmp_path / "pending_urls.txt"
    processed = tmp_path / "processed_urls.txt"
    _write_pending(pending, [])
    processed.touch()

    call_order: list[str] = []

    def fake_git_pull():
        call_order.append("git_pull")

    def fake_build_pipeline(*args, **kwargs):
        call_order.append("build_pipeline")
        store = MagicMock()
        store.count_pending.return_value = 0
        pipeline = MagicMock()
        pipeline.run_all.return_value = []
        return pipeline, store

    with (
        patch("runner.run_and_commit.git_pull", side_effect=fake_git_pull),
        patch("runner.run_and_commit.build_pipeline", side_effect=fake_build_pipeline),
    ):
        main()

    assert call_order[0] == "git_pull"
    assert call_order[1] == "build_pipeline"


# P3-02: git pull 後に pending が存在 → Pipeline.run_all() が呼ばれること
def test_p3_02_run_all_called_when_pending(tmp_path: Path) -> None:
    from runner.run_and_commit import main

    mock_pipeline = MagicMock()
    mock_pipeline.run_all.return_value = []
    mock_store = MagicMock()
    mock_store.count_pending.return_value = 2

    with (
        patch("runner.run_and_commit.git_pull"),
        patch("runner.run_and_commit.build_pipeline", return_value=(mock_pipeline, mock_store)),
    ):
        main()

    mock_pipeline.run_all.assert_called_once()


# P3-03: pending が空 → Pipeline は実行されず即座に終了
def test_p3_03_empty_pending_skips_pipeline(tmp_path: Path) -> None:
    from runner.run_and_commit import main

    mock_pipeline = MagicMock()
    mock_store = MagicMock()
    mock_store.count_pending.return_value = 0

    with (
        patch("runner.run_and_commit.git_pull"),
        patch("runner.run_and_commit.build_pipeline", return_value=(mock_pipeline, mock_store)),
    ):
        exit_code = main()

    mock_pipeline.run_all.assert_not_called()
    assert exit_code == 0


# P3-04: Pipeline 実行後 → output/ にファイルが生成されている
def test_p3_04_output_files_created(tmp_path: Path) -> None:
    from runner.run_and_commit import main
    from core.pipeline import PipelineResult

    output_dir = tmp_path / "output"
    output_dir.mkdir()
    output_file = output_dir / "AAAAAAAAAAA.txt"
    output_file.write_text("文字起こし結果", encoding="utf-8")

    mock_result = PipelineResult(url=URL_A, status="success", output_path=output_file)
    mock_pipeline = MagicMock()
    mock_pipeline.run_all.return_value = [mock_result]
    mock_store = MagicMock()
    mock_store.count_pending.return_value = 1

    with (
        patch("runner.run_and_commit.git_pull"),
        patch("runner.run_and_commit.build_pipeline", return_value=(mock_pipeline, mock_store)),
    ):
        exit_code = main()

    assert exit_code == 0
    assert output_file.exists()
    assert output_file.read_text(encoding="utf-8") == "文字起こし結果"


# git_pull が subprocess.run を使うことを検証
def test_git_pull_uses_subprocess(tmp_path: Path) -> None:
    from runner.run_and_commit import git_pull

    with patch("runner.run_and_commit.subprocess.run") as mock_run:
        git_pull()

    mock_run.assert_called_once_with(["git", "pull", "--rebase"], check=True)


# エラーがあった場合 exit_code が 1
def test_main_returns_1_on_error() -> None:
    from runner.run_and_commit import main
    from core.pipeline import PipelineResult

    mock_result = PipelineResult(url=URL_A, status="error", error="失敗")
    mock_pipeline = MagicMock()
    mock_pipeline.run_all.return_value = [mock_result]
    mock_store = MagicMock()
    mock_store.count_pending.return_value = 1

    with (
        patch("runner.run_and_commit.git_pull"),
        patch("runner.run_and_commit.build_pipeline", return_value=(mock_pipeline, mock_store)),
    ):
        exit_code = main()

    assert exit_code == 1
