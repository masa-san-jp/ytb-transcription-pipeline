# YouTube文字起こしパイプライン 実装仕様書

**バージョン:** 1.0.0
**最終更新:** 2025-04-26

-----

## 目次

1. [推奨動作環境](#1-推奨動作環境)
1. [アーキテクチャ概要](#2-アーキテクチャ概要)
1. [共通コアモジュール仕様](#3-共通コアモジュール仕様)
1. [Phase 1 — CLI Manual Mode](#4-phase-1--cli-manual-mode)
1. [Phase 2 — Watchdog Mode](#5-phase-2--watchdog-mode)
1. [Phase 3 — GitHub Actions Self-hosted Runner Mode](#6-phase-3--github-actions-self-hosted-runner-mode)
1. [テスト戦略](#7-テスト戦略)
1. [依存ライブラリ一覧](#8-依存ライブラリ一覧)
1. [ディレクトリ構成](#9-ディレクトリ構成)
1. [エラーコード定義](#10-エラーコード定義)

-----

## 1. 推奨動作環境

### 1-1. ハードウェア要件

|項目           |最小構成            |推奨構成              |備考                           |
|-------------|----------------|------------------|-----------------------------|
|チップ          |Apple M1        |Apple M3 Pro 以上   |Neural Engine必須。Intel Macは非対応|
|メモリ (Unified)|16 GB           |32 GB 以上          |large-v3は実行時に約10GBを使用        |
|ストレージ空き      |20 GB           |50 GB 以上          |モデルキャッシュ＋音声一時ファイル分を含む        |
|OS           |macOS 13 Ventura|macOS 14 Sonoma 以上|                             |


> **Note:** 128GB構成は余裕があるが必須ではない。32GB以上あれば実用的なスループットが得られる。16GBでも動作するが、大量バッチ処理時のスワップに注意。

### 1-2. ソフトウェア要件

|ソフトウェア              |バージョン   |用途              |
|--------------------|--------|----------------|
|Python              |3.11 以上 |ランタイム           |
|yt-dlp              |最新安定版   |音声抽出            |
|mlx-whisper         |0.4.0 以上|音声認識            |
|ffmpeg              |6.0 以上  |音声デコード（yt-dlp依存）|
|watchdog            |4.0 以上  |Phase 2以降       |
|GitHubActions Runner|最新安定版   |Phase 3のみ       |

-----

## 2. アーキテクチャ概要

```
┌─────────────────────────────────────────────────┐
│                   呼び出し層                      │
│  Phase1: CLI   Phase2: Watchdog  Phase3: Runner  │
└───────────────────┬─────────────────────────────┘
                    │
┌───────────────────▼─────────────────────────────┐
│               コアパイプライン                    │
│  URLLoader → Downloader → Transcriber → Writer  │
└─────────────────────────────────────────────────┘
```

各Phaseは共通コアを **変更せず** に呼び出す設計とする。コアへの変更はすべてのPhaseに影響するため、変更時は全Phaseのテストを通過させること。

-----

## 3. 共通コアモジュール仕様

### 3-1. モジュール構成

```
core/
├── url_store.py       # URLリストの読み書き（pending / processed）
├── downloader.py      # yt-dlp ラッパー、音声ファイル生成
├── transcriber.py     # mlx-whisper ラッパー、テキスト生成
├── writer.py          # 出力ファイル書き込み
└── pipeline.py        # 上記を順に呼び出すオーケストレーター
```

### 3-2. `url_store.py`

#### 責務

- `pending_urls.txt` からURLを1行1件として読み込む
- 処理済みURLを `processed_urls.txt` へアトミックに移動する
- 空行・重複・コメント行（`#`）を無視する

#### インターフェース

```python
class URLStore:
    def __init__(self, pending_path: Path, processed_path: Path) -> None: ...

    def pop_next(self) -> str | None:
        """未処理URLを1件取り出す。なければ None を返す。"""

    def mark_done(self, url: str) -> None:
        """処理済みとして processed_urls.txt へ追記する。"""

    def count_pending(self) -> int:
        """現在の未処理件数を返す。"""
```

#### 単体テスト要件（`tests/test_url_store.py`）

|テストID|条件                      |期待結果                                 |
|-----|------------------------|-------------------------------------|
|US-01|pending が空              |`pop_next()` が `None` を返す            |
|US-02|3件ある状態で `pop_next()` を呼ぶ|先頭URLを返し、pending から削除                |
|US-03|`mark_done()` 後         |processed_urls.txt に追記されている          |
|US-04|空行・`#`コメント行が混在          |無視され件数に含まれない                         |
|US-05|`mark_done()` 途中でクラッシュ想定|pending と processed の二重登録が発生しない（べき等性）|

-----

### 3-3. `downloader.py`

#### 責務

- yt-dlp を使って指定URLの音声を一時ファイル（`/tmp/yt_<uuid>.m4a`）に保存する
- 完了後、ファイルパスを返す
- 動画が削除・非公開・地域制限の場合は `VideoUnavailableError` を raise する
- 処理完了（成功・失敗問わず）後に一時ファイルを削除するクリーンアップを保証する（`try/finally`）

#### インターフェース

```python
class Downloader:
    def download(self, url: str) -> Path:
        """
        成功: 音声ファイルの Path を返す
        失敗: VideoUnavailableError | DownloadError を raise
        """

    def cleanup(self, path: Path) -> None:
        """一時ファイルを削除する。存在しない場合は無視。"""
```

#### カスタム例外

```python
class VideoUnavailableError(Exception):
    """動画が存在しない、非公開、または地域制限により取得不可"""

class DownloadError(Exception):
    """ネットワーク障害等、一時的なダウンロード失敗"""
```

#### 単体テスト要件（`tests/test_downloader.py`）

> **Note:** 実際のネットワーク通信は行わない。yt-dlp の呼び出しをモックする。

|テストID|条件                                     |期待結果                           |
|-----|---------------------------------------|-------------------------------|
|DL-01|yt-dlp が成功を返す                          |戻り値が `Path` オブジェクト             |
|DL-02|yt-dlp が `ERROR: Video unavailable` を返す|`VideoUnavailableError` が raise|
|DL-03|yt-dlp が `ERROR: Private video` を返す    |`VideoUnavailableError` が raise|
|DL-04|成功後に `cleanup()` を呼ぶ                   |一時ファイルが削除されている                 |
|DL-05|例外発生後も                                 |一時ファイルが削除されている（リソースリーク無し）      |

-----

### 3-4. `transcriber.py`

#### 責務

- 指定された音声ファイルを `mlx-whisper` で文字起こしする
- 言語は自動検出（`language=None`）を基本とし、オプションで指定可
- 結果を `TranscriptionResult` として返す

#### インターフェース

```python
@dataclass
class TranscriptionResult:
    text: str
    language: str
    segments: list[dict]  # mlx-whisper のネイティブ出力

class Transcriber:
    MODEL_ID = "mlx-community/whisper-large-v3-mlx"

    def __init__(self, model_id: str = MODEL_ID) -> None: ...

    def transcribe(self, audio_path: Path, language: str | None = None) -> TranscriptionResult: ...
```

#### 単体テスト要件（`tests/test_transcriber.py`）

> **Note:** mlx-whisper の推論呼び出しはモックする。実際の推論はIntegration Testで行う。

|テストID|条件                 |期待結果                               |
|-----|-------------------|-----------------------------------|
|TR-01|モックで正常な結果を返す       |`TranscriptionResult.text` が空でない   |
|TR-02|音声ファイルが存在しない       |`FileNotFoundError` が raise        |
|TR-03|`language="ja"` を指定|mlx-whisper に `language="ja"` が渡される|

-----

### 3-5. `pipeline.py`

#### 責務

- `URLStore`, `Downloader`, `Transcriber`, `Writer` を順に呼び出す
- `VideoUnavailableError` はスキップ（ログを出力し `mark_done()` せず次へ進む）
- `DownloadError` はリトライ（最大3回、指数バックオフ）
- 各ステップの開始・完了・スキップをログに記録する

#### インターフェース

```python
class Pipeline:
    def __init__(
        self,
        store: URLStore,
        downloader: Downloader,
        transcriber: Transcriber,
        writer: Writer,
        logger: logging.Logger | None = None,
    ) -> None: ...

    def run_once(self) -> PipelineResult:
        """pending から1件取り出し、処理して結果を返す。"""

    def run_all(self) -> list[PipelineResult]:
        """pending が空になるまでループする。"""
```

#### 単体テスト要件（`tests/test_pipeline.py`）

|テストID|条件                        |期待結果                                       |
|-----|--------------------------|-------------------------------------------|
|PP-01|正常フロー                     |`PipelineResult.status == "success"`       |
|PP-02|`VideoUnavailableError` 発生|スキップされ次のURLへ進む。processed には追加されない          |
|PP-03|`DownloadError` が3回連続     |リトライ3回後に `PipelineResult.status == "error"`|
|PP-04|pending が空                |`run_once()` が即座に `status == "empty"` を返す  |
|PP-05|処理中にクラッシュ                 |一時ファイルが残存しない                               |

-----

## 4. Phase 1 — CLI Manual Mode

### 4-1. 概要

ターミナルから手動で起動するバッチ処理モード。大量の過去動画処理に最適。

### 4-2. エントリーポイント

```
cli/
└── run.py
```

#### 起動コマンド

```bash
# 基本実行（スリープ防止を含む）
caffeinate -i python cli/run.py

# 出力先を指定
caffeinate -i python cli/run.py --output-dir ./output

# ドライラン（ダウンロード・文字起こしを行わず件数確認のみ）
python cli/run.py --dry-run
```

#### CLIオプション定義

|オプション         |デフォルト                               |説明           |
|--------------|------------------------------------|-------------|
|`--pending`   |`./pending_urls.txt`                |未処理URLリストのパス |
|`--processed` |`./processed_urls.txt`              |処理済みURLリストのパス|
|`--output-dir`|`./output`                          |文字起こしテキストの出力先|
|`--model`     |`mlx-community/whisper-large-v3-mlx`|Whisperモデル識別子|
|`--language`  |`None`（自動検出）                        |強制指定する言語コード  |
|`--dry-run`   |`False`                             |件数確認のみ実行     |
|`--log-level` |`INFO`                              |ログレベル        |

### 4-3. 出力仕様

- ファイル名: `{動画タイトル}_{動画ID}.txt`（ファイルシステム非対応文字はアンダースコアに置換）
- エンコーディング: UTF-8
- 内容: 文字起こし全文テキスト

### 4-4. コンソール出力仕様

```
[1/5] 処理中: https://www.youtube.com/watch?v=XXXXX
      タイトル: サンプル動画タイトル
      ダウンロード完了 (32.4 MB)
      文字起こし完了 (2m 14s)
      → output/サンプル動画タイトル_XXXXX.txt

[2/5] スキップ: https://www.youtube.com/watch?v=YYYYY
      理由: 動画が削除済みまたは非公開

完了: 4件成功 / 1件スキップ / 0件エラー
```

### 4-5. Phase 1 統合テスト要件（`tests/integration/test_phase1.py`）

> **Note:** 実際のネットワーク通信は行わない。yt-dlp と mlx-whisper をモックする。

|テストID|条件                     |期待結果                  |
|-----|-----------------------|----------------------|
|P1-01|pending に3件、全て正常       |output/ に3ファイル生成      |
|P1-02|pending に3件、うち1件が非公開URL|2件成功、1件スキップ、exitcode 0|
|P1-03|`--dry-run` 指定         |ファイル生成なし、件数のみ出力       |
|P1-04|output/ が存在しない         |自動作成されてから書き込まれる       |

-----

## 5. Phase 2 — Watchdog Mode

> **前提:** Phase 1の全テストが通過していること。コアモジュールには変更を加えない。

### 5-1. 概要

Mac上で常駐し、`pending_urls.txt` の変更を検知して自動実行するデーモンモード。iCloud Drive / Dropbox / Google Drive の同期フォルダと組み合わせることで、スマホからの遠隔操作を実現する。

### 5-2. エントリーポイント

```
watchdog_mode/
└── watcher.py
```

#### 起動コマンド

```bash
caffeinate -i python watchdog_mode/watcher.py --watch-dir ~/Library/Mobile\ Documents/com~apple~CloudDocs/transcribe
```

#### Watchdogオプション定義

|オプション           |デフォルト               |説明                      |
|----------------|--------------------|------------------------|
|`--watch-dir`   |`.`                 |監視対象ディレクトリ              |
|`--debounce-sec`|`3.0`               |ファイル変更検知後の待機秒数（連続書き込み対策）|
|`--output-dir`  |`{watch-dir}/output`|文字起こしテキストの出力先           |

### 5-3. 動作フロー

```
起動
 │
 └─► ディレクトリを監視開始
         │
         └─► pending_urls.txt の変更を検知
                 │
                 ├─► debounce 待機（同期ソフトの連続イベント対策）
                 │
                 └─► Pipeline.run_all() を実行
                         │
                         └─► 完了後、待機に戻る（多重起動を防止）
```

### 5-4. 多重起動防止

同一ディレクトリに対して処理が実行中の場合、新たな変更イベントはキューに積まず破棄する。処理完了後に pending が残っていれば再実行する。

```python
# 擬似コード
is_running = threading.Event()

def on_file_change():
    if is_running.is_set():
        return  # 実行中はスキップ
    is_running.set()
    try:
        pipeline.run_all()
    finally:
        is_running.clear()
        if store.count_pending() > 0:
            on_file_change()  # 完了後に残があれば再実行
```

### 5-5. Phase 2 テスト要件（`tests/test_watcher.py`）

|テストID|条件                 |期待結果               |
|-----|-------------------|-------------------|
|WD-01|ファイル変更イベントを送出      |Pipeline が1回実行される  |
|WD-02|実行中に再度変更イベントを送出    |多重起動しない            |
|WD-03|debounce 時間内に複数イベント|Pipeline は1回しか起動しない|
|WD-04|処理完了後に pending が残る |自動的に再実行される         |

-----

## 6. Phase 3 — GitHub Actions Self-hosted Runner Mode

> **前提:** Phase 2の全テストが通過していること。コアモジュールには変更を加えない。

### 6-1. 概要

GitHubリポジトリをコマンド&コントロール基盤として使用する。Macがオフラインでも指示をキューイングでき、次回起動時に自動的にタスクを消化する。

### 6-2. リポジトリ構成

```
repo/
├── .github/
│   └── workflows/
│       └── transcribe.yml    # ワークフロー定義
├── pending_urls.txt           # 未処理URLリスト（GitHubから編集）
├── processed_urls.txt         # 処理済みURLリスト（自動更新）
├── output/                    # 文字起こし結果（自動コミット）
│   └── .gitkeep
└── runner/
    └── run_and_commit.py      # Runner用エントリーポイント
```

### 6-3. GitHub Actionsワークフロー定義

```yaml
# .github/workflows/transcribe.yml
name: YouTube Transcription

on:
  push:
    paths:
      - 'pending_urls.txt'
  workflow_dispatch:

jobs:
  transcribe:
    runs-on: self-hosted
    timeout-minutes: 360

    steps:
      - name: Checkout
        uses: actions/checkout@v4
        with:
          fetch-depth: 0

      - name: Run pipeline
        run: |
          caffeinate -i python runner/run_and_commit.py

      - name: Commit results
        run: |
          git config user.name  "github-actions[bot]"
          git config user.email "github-actions[bot]@users.noreply.github.com"
          git add processed_urls.txt output/
          git diff --cached --quiet || git commit -m "chore: transcription results [skip ci]"
          git push
```

> **`[skip ci]`** コミットメッセージに付与することで、結果のpushが新たなワークフローをトリガーしないようにする。

### 6-4. `runner/run_and_commit.py`

```python
# 責務: git pullで最新状態を取得してからPipelineを実行する
# コミット・プッシュはワークフローのshellステップが担うため、
# このスクリプトはパイプライン実行のみに責任を持つ

def main():
    subprocess.run(["git", "pull", "--rebase"], check=True)
    pipeline = build_pipeline(
        pending_path=Path("pending_urls.txt"),
        processed_path=Path("processed_urls.txt"),
        output_dir=Path("output"),
    )
    results = pipeline.run_all()
    print_summary(results)
```

### 6-5. セルフホストRunner セットアップ手順

1. GitHubリポジトリの **Settings > Actions > Runners > New self-hosted runner** を開く
1. macOS 用のダウンロードコマンドを実行
1. `./config.sh --url <repo_url> --token <token>` を実行
1. ログインシェルでの自動起動を設定:

```bash
# launchd サービスとして登録（Mac再起動後も自動起動）
./svc.sh install
./svc.sh start
```

### 6-6. Phase 3 テスト要件（`tests/integration/test_phase3.py`）

|テストID|条件                     |期待結果                      |
|-----|-----------------------|--------------------------|
|P3-01|`run_and_commit.py` を実行|`git pull` が先に呼ばれること      |
|P3-02|git pull 後に pending が存在|Pipeline.run_all() が呼ばれること|
|P3-03|pending が空             |Pipeline は実行されず即座に終了      |
|P3-04|Pipeline 実行後           |output/ にファイルが生成されている     |

-----

## 7. テスト戦略

### 7-1. テストの階層

```
tests/
├── unit/
│   ├── test_url_store.py
│   ├── test_downloader.py
│   ├── test_transcriber.py
│   └── test_pipeline.py
├── integration/
│   ├── test_phase1.py
│   ├── test_phase2.py   （watchdog イベントシミュレーション）
│   └── test_phase3.py
└── fixtures/
    ├── pending_urls_sample.txt
    ├── mock_audio.m4a           # 実際の推論用（CI不要）
    └── mock_transcription.json  # mlx-whisperのモック出力
```

### 7-2. モック方針

|依存コンポーネント  |モック方法                     |理由             |
|-----------|--------------------------|---------------|
|yt-dlp     |`unittest.mock.patch`     |ネットワーク不要、速度    |
|mlx-whisper|`unittest.mock.patch`     |GPU不要、CI環境で動作可能|
|Git コマンド   |`subprocess` をモック         |実リポジトリ不要       |
|ファイルシステム   |`tmp_path`（pytest fixture）|テスト間の干渉防止      |

### 7-3. CI実行環境の考慮

単体・統合テストはモックにより **Apple Siliconなしの環境（GitHub Actions ubuntu-latest等）でも実行可能** に設計する。

実際のlarge-v3モデルを使う推論テストは `tests/e2e/` に分離し、ローカル環境でのみ手動実行とする。

```bash
# 全テスト（モックあり）
pytest tests/unit tests/integration

# E2Eテスト（Apple Siliconのみ）
pytest tests/e2e -m "apple_silicon"
```

### 7-4. カバレッジ基準

|スコープ            |目標カバレッジ|
|----------------|-------|
|`core/`         |90% 以上 |
|`cli/`          |80% 以上 |
|`watchdog_mode/`|80% 以上 |
|`runner/`       |80% 以上 |

```bash
pytest --cov=core --cov=cli --cov=watchdog_mode --cov=runner \
       --cov-report=term-missing --cov-fail-under=80
```

-----

## 8. 依存ライブラリ一覧

### `requirements.txt`

```
yt-dlp>=2024.1.0
mlx-whisper>=0.4.0
watchdog>=4.0.0
```

### `requirements-dev.txt`

```
pytest>=8.0.0
pytest-cov>=5.0.0
pytest-mock>=3.14.0
```

### インストール手順

```bash
# ffmpeg（Homebrewで管理）
brew install ffmpeg

# Python依存
pip install -r requirements.txt

# 開発依存
pip install -r requirements-dev.txt
```

-----

## 9. ディレクトリ構成

```
youtube-transcription/
├── core/
│   ├── __init__.py
│   ├── url_store.py
│   ├── downloader.py
│   ├── transcriber.py
│   ├── writer.py
│   └── pipeline.py
├── cli/
│   ├── __init__.py
│   └── run.py
├── watchdog_mode/
│   ├── __init__.py
│   └── watcher.py
├── runner/
│   ├── __init__.py
│   └── run_and_commit.py
├── tests/
│   ├── unit/
│   ├── integration/
│   ├── e2e/
│   └── fixtures/
├── output/
│   └── .gitkeep
├── pending_urls.txt
├── processed_urls.txt
├── requirements.txt
├── requirements-dev.txt
└── README.md
```

-----

## 10. エラーコード定義

|エラーコード|例外クラス                  |説明             |対応              |
|------|-----------------------|---------------|----------------|
|`E001`|`VideoUnavailableError`|動画が削除・非公開・地域制限 |スキップして次のURLへ    |
|`E002`|`DownloadError`        |ネットワーク障害等の一時エラー|最大3回リトライ後にスキップ  |
|`E003`|`TranscriptionError`   |mlx-whisper が失敗|スキップして次のURLへ    |
|`E004`|`WriteError`           |出力先への書き込み失敗    |処理を中断、exitcode 1|
|`E005`|`StoreCorruptedError`  |URLリストファイルが破損  |処理を中断、exitcode 1|


> `E004` および `E005` のみが **処理全体の中断** を引き起こす。それ以外はすべて **継続実行（skip）** する。
