from __future__ import annotations

import threading
import time
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from watchdog.events import FileModifiedEvent, FileCreatedEvent

from watchdog_mode.watcher import _PendingFileHandler, build_pipeline, build_arg_parser, main


_PENDING = "pending_urls.txt"


def _make_handler(
    tmp_path: Path,
    debounce_sec: float = 0.05,
    run_all_side_effect=None,
) -> tuple[_PendingFileHandler, MagicMock, MagicMock]:
    pipeline = MagicMock()
    store = MagicMock()
    store.count_pending.return_value = 0
    if run_all_side_effect is not None:
        pipeline.run_all.side_effect = run_all_side_effect
    import logging
    handler = _PendingFileHandler(
        pipeline=pipeline,
        store=store,
        debounce_sec=debounce_sec,
        logger=logging.getLogger("test"),
    )
    return handler, pipeline, store


def _fire(handler: _PendingFileHandler, watch_dir: Path) -> None:
    event = FileModifiedEvent(str(watch_dir / _PENDING))
    handler.on_modified(event)


def _wait(sec: float = 0.2) -> None:
    time.sleep(sec)


# WD-01: ファイル変更イベントを送出 → Pipeline が1回実行される
def test_wd01_file_change_triggers_pipeline(tmp_path: Path) -> None:
    handler, pipeline, _ = _make_handler(tmp_path, debounce_sec=0.05)

    _fire(handler, tmp_path)
    _wait(0.2)

    pipeline.run_all.assert_called_once()


# WD-02: 実行中に再度変更イベントを送出 → 多重起動しない
def test_wd02_no_concurrent_execution(tmp_path: Path) -> None:
    started = threading.Event()
    released = threading.Event()

    def slow_run_all():
        started.set()
        released.wait(timeout=2.0)

    handler, pipeline, _ = _make_handler(tmp_path, debounce_sec=0.05, run_all_side_effect=slow_run_all)

    _fire(handler, tmp_path)
    started.wait(timeout=1.0)  # 1回目が走り始めるまで待つ

    # 実行中に2回目のイベント
    _fire(handler, tmp_path)
    _wait(0.15)  # debounce 後も実行されないことを確認

    released.set()
    _wait(0.1)

    # run_all は1回だけ呼ばれるはず
    assert pipeline.run_all.call_count == 1


# WD-03: debounce 時間内に複数イベント → Pipeline は1回しか起動しない
def test_wd03_debounce_coalesces_events(tmp_path: Path) -> None:
    handler, pipeline, _ = _make_handler(tmp_path, debounce_sec=0.15)

    # debounce 内で3連続イベント
    for _ in range(3):
        _fire(handler, tmp_path)
        time.sleep(0.03)

    _wait(0.4)  # debounce + 実行完了を待つ

    pipeline.run_all.assert_called_once()


# WD-04: 処理完了後に pending が残る → 自動的に再実行される
def test_wd04_reruns_if_pending_remains(tmp_path: Path) -> None:
    call_count = 0

    def run_all_with_remaining():
        nonlocal call_count
        call_count += 1

    handler, pipeline, store = _make_handler(tmp_path, debounce_sec=0.05)
    # 1回目完了後だけ pending あり、2回目以降はゼロ
    store.count_pending.side_effect = [1, 0]
    pipeline.run_all.side_effect = run_all_with_remaining

    _fire(handler, tmp_path)
    _wait(0.4)

    assert pipeline.run_all.call_count == 2


# 無関係ファイルの変更は無視される（補足テスト）
def test_wd_irrelevant_file_ignored(tmp_path: Path) -> None:
    handler, pipeline, _ = _make_handler(tmp_path, debounce_sec=0.05)

    event = FileModifiedEvent(str(tmp_path / "other_file.txt"))
    handler.on_modified(event)
    _wait(0.2)

    pipeline.run_all.assert_not_called()


# build_pipeline が URLStore / Pipeline を正しく構成する
def test_build_pipeline_creates_components(tmp_path: Path) -> None:
    from core.pipeline import Pipeline
    from core.url_store import URLStore

    (tmp_path / "pending_urls.txt").touch()
    (tmp_path / "processed_urls.txt").touch()

    pipeline, store = build_pipeline(
        watch_dir=tmp_path,
        output_dir=tmp_path / "output",
        model="mlx-community/whisper-large-v3-mlx",
    )

    assert isinstance(pipeline, Pipeline)
    assert isinstance(store, URLStore)
    assert store.pending_path == tmp_path / "pending_urls.txt"


# build_arg_parser のデフォルト値検証
def test_build_arg_parser_defaults() -> None:
    args = build_arg_parser().parse_args([])
    assert args.watch_dir == Path(".")
    assert args.debounce_sec == 3.0
    assert args.output_dir is None
    assert args.log_level == "INFO"


# main() が正常起動して KeyboardInterrupt で終了する
def test_main_starts_and_stops(tmp_path: Path) -> None:
    from unittest.mock import MagicMock

    fake_observer = MagicMock()

    with (
        patch("watchdog_mode.watcher.Observer", return_value=fake_observer),
        patch("watchdog_mode.watcher.build_pipeline") as mock_bp,
        patch("watchdog_mode.watcher.time.sleep", side_effect=KeyboardInterrupt),
    ):
        mock_pipeline = MagicMock()
        mock_store = MagicMock()
        mock_bp.return_value = (mock_pipeline, mock_store)

        exit_code = main(["--watch-dir", str(tmp_path), "--debounce-sec", "0.1"])

    assert exit_code == 0
    fake_observer.start.assert_called_once()
    fake_observer.stop.assert_called_once()
    fake_observer.join.assert_called_once()
