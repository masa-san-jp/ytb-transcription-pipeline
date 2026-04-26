from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

from core.downloader import Downloader
from core.pipeline import Pipeline, PipelineResult
from core.transcriber import Transcriber
from core.url_store import URLStore
from core.writer import Writer


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="YouTube文字起こしパイプライン (Phase 1: CLIモード)")
    parser.add_argument("--pending", type=Path, default=Path("pending_urls.txt"), help="未処理URLリストのパス")
    parser.add_argument("--processed", type=Path, default=Path("processed_urls.txt"), help="処理済みURLリストのパス")
    parser.add_argument("--output-dir", type=Path, default=Path("output"), help="文字起こしテキストの出力先")
    parser.add_argument("--model", default=Transcriber.MODEL_ID, help="Whisperモデル識別子")
    parser.add_argument("--language", default=None, help="強制指定する言語コード")
    parser.add_argument("--dry-run", action="store_true", help="件数確認のみ実行")
    parser.add_argument("--log-level", default="INFO", choices=["DEBUG", "INFO", "WARNING", "ERROR"], help="ログレベル")
    return parser


def setup_logging(level: str) -> None:
    logging.basicConfig(
        level=getattr(logging, level),
        format="%(asctime)s [%(levelname)s] %(message)s",
        datefmt="%H:%M:%S",
    )


def print_summary(results: list[PipelineResult]) -> None:
    success = sum(1 for r in results if r.status == "success")
    skipped = sum(1 for r in results if r.status == "skip")
    errors = sum(1 for r in results if r.status == "error")
    print(f"\n完了: {success}件成功 / {skipped}件スキップ / {errors}件エラー")


def main(argv: list[str] | None = None) -> int:
    parser = build_arg_parser()
    args = parser.parse_args(argv)
    setup_logging(args.log_level)

    store = URLStore(pending_path=args.pending, processed_path=args.processed)
    count = store.count_pending()

    if args.dry_run:
        print(f"未処理件数: {count}件")
        return 0

    if count == 0:
        print("未処理URLがありません。")
        return 0

    downloader = Downloader()
    transcriber = Transcriber(model_id=args.model)
    writer = Writer(output_dir=args.output_dir)

    total = count
    results: list[PipelineResult] = []
    idx = 0

    pipeline = Pipeline(store=store, downloader=downloader, transcriber=transcriber, writer=writer)

    while True:
        idx += 1
        print(f"\n[{idx}/{total}] 処理中...")
        result = pipeline.run_once()
        if result.status == "empty":
            break
        results.append(result)
        if result.status == "success":
            print(f"      → {result.output_path}")
        elif result.status == "skip":
            print(f"      スキップ: {result.error}")
        else:
            print(f"      エラー: {result.error}")

    print_summary(results)

    has_error = any(r.status == "error" for r in results)
    return 1 if has_error else 0


if __name__ == "__main__":
    sys.exit(main())
