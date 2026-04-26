from __future__ import annotations

import argparse
import logging
import sys
import threading
import time
from pathlib import Path

from watchdog.events import FileSystemEvent, FileSystemEventHandler
from watchdog.observers import Observer

from core.downloader import Downloader
from core.pipeline import Pipeline
from core.transcriber import Transcriber
from core.url_store import URLStore
from core.writer import Writer

_PENDING_FILENAME = "pending_urls.txt"


class _PendingFileHandler(FileSystemEventHandler):
    def __init__(
        self,
        pipeline: Pipeline,
        store: URLStore,
        debounce_sec: float,
        logger: logging.Logger,
    ) -> None:
        self._pipeline = pipeline
        self._store = store
        self._debounce_sec = debounce_sec
        self._logger = logger
        self._is_running = threading.Event()
        self._debounce_timer: threading.Timer | None = None
        self._lock = threading.Lock()

    def on_modified(self, event: FileSystemEvent) -> None:
        if event.is_directory:
            return
        if Path(event.src_path).name != _PENDING_FILENAME:
            return
        self._schedule_run()

    on_created = on_modified

    def _schedule_run(self) -> None:
        with self._lock:
            if self._debounce_timer is not None:
                self._debounce_timer.cancel()
            self._debounce_timer = threading.Timer(self._debounce_sec, self._try_run)
            self._debounce_timer.daemon = True
            self._debounce_timer.start()

    def _try_run(self) -> None:
        if self._is_running.is_set():
            self._logger.debug("実行中のためスキップ")
            return
        self._is_running.set()
        try:
            while True:
                self._logger.info("Pipeline 実行開始")
                self._pipeline.run_all()
                self._logger.info("Pipeline 実行完了")
                if self._store.count_pending() == 0:
                    break
                self._logger.info("残存URLあり — 再実行")
        finally:
            self._is_running.clear()


def build_pipeline(watch_dir: Path, output_dir: Path, model: str) -> tuple[Pipeline, URLStore]:
    pending_path = watch_dir / _PENDING_FILENAME
    processed_path = watch_dir / "processed_urls.txt"
    store = URLStore(pending_path=pending_path, processed_path=processed_path)
    downloader = Downloader()
    transcriber = Transcriber(model_id=model)
    writer = Writer(output_dir=output_dir)
    pipeline = Pipeline(store=store, downloader=downloader, transcriber=transcriber, writer=writer)
    return pipeline, store


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="YouTube文字起こしパイプライン (Phase 2: Watchdogモード)")
    parser.add_argument("--watch-dir", type=Path, default=Path("."), help="監視対象ディレクトリ")
    parser.add_argument("--debounce-sec", type=float, default=3.0, help="ファイル変更検知後の待機秒数")
    parser.add_argument("--output-dir", type=Path, default=None, help="文字起こしテキストの出力先 (デフォルト: {watch-dir}/output)")
    parser.add_argument("--model", default=Transcriber.MODEL_ID, help="Whisperモデル識別子")
    parser.add_argument("--log-level", default="INFO", choices=["DEBUG", "INFO", "WARNING", "ERROR"], help="ログレベル")
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_arg_parser()
    args = parser.parse_args(argv)

    logging.basicConfig(
        level=getattr(logging, args.log_level),
        format="%(asctime)s [%(levelname)s] %(message)s",
        datefmt="%H:%M:%S",
    )
    logger = logging.getLogger(__name__)

    watch_dir: Path = args.watch_dir.resolve()
    output_dir: Path = (args.output_dir or watch_dir / "output").resolve()

    pipeline, store = build_pipeline(watch_dir=watch_dir, output_dir=output_dir, model=args.model)
    handler = _PendingFileHandler(
        pipeline=pipeline,
        store=store,
        debounce_sec=args.debounce_sec,
        logger=logger,
    )

    observer = Observer()
    observer.schedule(handler, str(watch_dir), recursive=False)
    observer.start()
    logger.info("監視開始: %s (debounce=%.1fs)", watch_dir, args.debounce_sec)

    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        pass
    finally:
        observer.stop()
        observer.join()
        logger.info("監視停止")

    return 0


if __name__ == "__main__":
    sys.exit(main())
