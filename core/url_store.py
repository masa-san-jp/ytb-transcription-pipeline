from __future__ import annotations

import fcntl
from pathlib import Path


class URLStore:
    def __init__(self, pending_path: Path, processed_path: Path) -> None:
        self.pending_path = pending_path
        self.processed_path = processed_path
        self.pending_path.touch(exist_ok=True)
        self.processed_path.touch(exist_ok=True)

    def _read_urls(self) -> list[str]:
        lines = self.pending_path.read_text(encoding="utf-8").splitlines()
        return [l.strip() for l in lines if l.strip() and not l.strip().startswith("#")]

    def pop_next(self) -> str | None:
        with self.pending_path.open("r+", encoding="utf-8") as f:
            fcntl.flock(f, fcntl.LOCK_EX)
            lines = f.readlines()
            urls = []
            non_url_lines = []
            for line in lines:
                stripped = line.strip()
                if stripped and not stripped.startswith("#"):
                    urls.append(stripped)
                else:
                    non_url_lines.append(line)
            if not urls:
                return None
            next_url = urls[0]
            remaining = urls[1:]
            f.seek(0)
            f.truncate()
            for line in non_url_lines:
                f.write(line)
            for url in remaining:
                f.write(url + "\n")
        return next_url

    def mark_done(self, url: str) -> None:
        with self.processed_path.open("a", encoding="utf-8") as f:
            fcntl.flock(f, fcntl.LOCK_EX)
            f.write(url + "\n")

    def count_pending(self) -> int:
        return len(self._read_urls())
