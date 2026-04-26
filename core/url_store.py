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
            next_url: str | None = None
            remaining_lines = []
            for line in lines:
                stripped = line.strip()
                if next_url is None and stripped and not stripped.startswith("#"):
                    next_url = stripped
                    continue
                remaining_lines.append(line)
            if next_url is None:
                return None
            f.seek(0)
            f.truncate()
            for line in remaining_lines:
                f.write(line)
        return next_url

    def mark_done(self, url: str) -> None:
        with self.processed_path.open("a", encoding="utf-8") as f:
            fcntl.flock(f, fcntl.LOCK_EX)
            f.write(url + "\n")

    def count_pending(self) -> int:
        return len(self._read_urls())
