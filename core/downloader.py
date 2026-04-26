from __future__ import annotations

import subprocess
import uuid
from pathlib import Path


class VideoUnavailableError(Exception):
    """動画が存在しない、非公開、または地域制限により取得不可"""


class DownloadError(Exception):
    """ネットワーク障害等、一時的なダウンロード失敗"""


_UNAVAILABLE_PATTERNS = (
    "Video unavailable",
    "Private video",
    "This video is private",
    "This video has been removed",
)


class Downloader:
    def download(self, url: str) -> Path:
        tmp_path = Path(f"/tmp/yt_{uuid.uuid4().hex}.m4a")
        try:
            result = subprocess.run(
                [
                    "yt-dlp",
                    "--extract-audio",
                    "--audio-format", "m4a",
                    "--output", str(tmp_path),
                    "--no-playlist",
                    url,
                ],
                capture_output=True,
                text=True,
            )
            stderr = result.stderr + result.stdout
            if result.returncode != 0:
                for pattern in _UNAVAILABLE_PATTERNS:
                    if pattern in stderr:
                        raise VideoUnavailableError(f"動画が利用不可: {url}\n{stderr}")
                raise DownloadError(f"ダウンロード失敗: {url}\n{stderr}")
            if not tmp_path.exists():
                raise DownloadError(f"出力ファイルが見つかりません: {tmp_path}")
            return tmp_path
        except (VideoUnavailableError, DownloadError):
            self.cleanup(tmp_path)
            raise
        except Exception as e:
            self.cleanup(tmp_path)
            raise DownloadError(f"予期しないエラー: {e}") from e

    def cleanup(self, path: Path) -> None:
        try:
            path.unlink(missing_ok=True)
        except OSError:
            pass
