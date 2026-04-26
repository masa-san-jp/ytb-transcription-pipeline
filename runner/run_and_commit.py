from __future__ import annotations

import subprocess
import sys
from pathlib import Path

from core.downloader import Downloader
from core.pipeline import Pipeline, PipelineResult
from core.transcriber import Transcriber
from core.url_store import URLStore
from core.writer import Writer


def git_pull() -> None:
    subprocess.run(["git", "pull", "--rebase"], check=True)


def build_pipeline(
    pending_path: Path,
    processed_path: Path,
    output_dir: Path,
    model: str = Transcriber.MODEL_ID,
) -> tuple[Pipeline, URLStore]:
    store = URLStore(pending_path=pending_path, processed_path=processed_path)
    downloader = Downloader()
    transcriber = Transcriber(model_id=model)
    writer = Writer(output_dir=output_dir)
    pipeline = Pipeline(store=store, downloader=downloader, transcriber=transcriber, writer=writer)
    return pipeline, store


def print_summary(results: list[PipelineResult]) -> None:
    success = sum(1 for r in results if r.status == "success")
    skipped = sum(1 for r in results if r.status == "skip")
    errors = sum(1 for r in results if r.status == "error")
    print(f"完了: {success}件成功 / {skipped}件スキップ / {errors}件エラー")


def main() -> int:
    try:
        git_pull()
    except subprocess.CalledProcessError as e:
        print(f"git pull 失敗: {e}", file=sys.stderr)
        return 1

    pipeline, store = build_pipeline(
        pending_path=Path("pending_urls.txt"),
        processed_path=Path("processed_urls.txt"),
        output_dir=Path("output"),
    )

    if store.count_pending() == 0:
        print("未処理URLがありません。")
        return 0

    results = pipeline.run_all()
    print_summary(results)

    has_error = any(r.status == "error" for r in results)
    return 1 if has_error else 0


if __name__ == "__main__":
    sys.exit(main())
