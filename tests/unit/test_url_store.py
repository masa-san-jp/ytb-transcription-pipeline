from __future__ import annotations

import pytest
from pathlib import Path

from core.url_store import URLStore


@pytest.fixture
def store(tmp_path: Path) -> URLStore:
    pending = tmp_path / "pending.txt"
    processed = tmp_path / "processed.txt"
    return URLStore(pending_path=pending, processed_path=processed)


def _fill_pending(store: URLStore, urls: list[str]) -> None:
    store.pending_path.write_text("\n".join(urls) + "\n", encoding="utf-8")


# US-01: pending が空の場合 pop_next() が None を返す
def test_us01_empty_returns_none(store: URLStore) -> None:
    assert store.pop_next() is None


# US-02: 3件ある状態で pop_next() を呼ぶと先頭URLを返し pending から削除
def test_us02_pop_next_returns_first_and_removes(store: URLStore) -> None:
    urls = [
        "https://www.youtube.com/watch?v=AAA",
        "https://www.youtube.com/watch?v=BBB",
        "https://www.youtube.com/watch?v=CCC",
    ]
    _fill_pending(store, urls)

    result = store.pop_next()

    assert result == urls[0]
    assert store.count_pending() == 2
    remaining = store.pending_path.read_text(encoding="utf-8")
    assert urls[0] not in remaining
    assert urls[1] in remaining


# US-03: mark_done() 後に processed_urls.txt に追記されている
def test_us03_mark_done_appends_to_processed(store: URLStore) -> None:
    url = "https://www.youtube.com/watch?v=AAA"

    store.mark_done(url)

    content = store.processed_path.read_text(encoding="utf-8")
    assert url in content


# US-04: 空行・#コメント行が混在しても無視され件数に含まれない
def test_us04_ignores_blank_and_comment_lines(store: URLStore) -> None:
    store.pending_path.write_text(
        "# コメント行\n"
        "https://www.youtube.com/watch?v=AAA\n"
        "\n"
        "# 別のコメント\n"
        "https://www.youtube.com/watch?v=BBB\n"
        "\n",
        encoding="utf-8",
    )

    assert store.count_pending() == 2


# US-05: べき等性 — 同じURLを2回 mark_done() しても pending に残らない
def test_us05_idempotent_mark_done(store: URLStore) -> None:
    url = "https://www.youtube.com/watch?v=AAA"
    _fill_pending(store, [url])

    store.pop_next()
    store.mark_done(url)
    store.mark_done(url)  # 2回目

    assert store.count_pending() == 0
    content = store.processed_path.read_text(encoding="utf-8")
    assert content.count(url) == 2  # 重複追記は許容するが pending からは消えている
