# YouTube文字起こしパイプライン

YouTube動画のURLリストから音声を取得し、[mlx-whisper](https://github.com/ml-explore/mlx-examples/tree/main/whisper)（Apple Silicon最適化）で文字起こしするパイプラインです。

## 動作環境

| 項目 | 最小 | 推奨 |
|------|------|------|
| チップ | Apple M1 | Apple M3 Pro 以上 |
| メモリ | 16 GB | 32 GB 以上 |
| OS | macOS 13 Ventura | macOS 14 Sonoma 以上 |
| Python | 3.11 以上 | — |

## セットアップ

```bash
brew install ffmpeg
pip install -r requirements.txt
```

開発・テスト用:

```bash
pip install -r requirements-dev.txt
```

---

## Phase 1 — CLI手動モード

`pending_urls.txt` に記載したURLをまとめて文字起こしします。

### 使い方

```bash
# 基本実行（スリープ防止）
caffeinate -i python cli/run.py

# 出力先を指定
caffeinate -i python cli/run.py --output-dir ./output

# 件数確認のみ（ダウンロード・文字起こしなし）
python cli/run.py --dry-run
```

### オプション

| オプション | デフォルト | 説明 |
|-----------|-----------|------|
| `--pending` | `./pending_urls.txt` | 未処理URLリストのパス |
| `--processed` | `./processed_urls.txt` | 処理済みURLリストのパス |
| `--output-dir` | `./output` | 文字起こしテキストの出力先 |
| `--model` | `mlx-community/whisper-large-v3-mlx` | Whisperモデル識別子 |
| `--language` | 自動検出 | 強制指定する言語コード（例: `ja`） |
| `--dry-run` | `False` | 件数確認のみ実行 |
| `--log-level` | `INFO` | ログレベル |

### pending_urls.txt の書き方

```
# コメント行は無視されます
https://www.youtube.com/watch?v=XXXXXXXXXXX
https://www.youtube.com/watch?v=YYYYYYYYYYY
```

### 出力

`output/{タイトル}_{動画ID}.txt` に UTF-8 テキストとして保存されます。

---

## Phase 2 — Watchdogデーモンモード

`pending_urls.txt` の変更を監視し、URLが追加されると自動的に処理を開始します。iCloud Drive / Dropbox などのクラウド同期フォルダと組み合わせることで、スマートフォンからの遠隔操作が可能です。

### 使い方

```bash
# iCloud Drive の監視フォルダを指定
caffeinate -i python watchdog_mode/watcher.py \
  --watch-dir ~/Library/Mobile\ Documents/com~apple~CloudDocs/transcribe
```

### オプション

| オプション | デフォルト | 説明 |
|-----------|-----------|------|
| `--watch-dir` | `.` | 監視対象ディレクトリ |
| `--debounce-sec` | `3.0` | ファイル変更検知後の待機秒数 |
| `--output-dir` | `{watch-dir}/output` | 文字起こしテキストの出力先 |
| `--model` | `mlx-community/whisper-large-v3-mlx` | Whisperモデル識別子 |

---

## Phase 3 — GitHub Actions セルフホストRunnerモード

GitHubリポジトリを司令塔として使います。`pending_urls.txt` をプッシュするとMac上のRunnerが自動起動し、結果をコミットして返します。Macがオフライン中でも指示をキューイングできます。

### セットアップ

1. GitHub リポジトリの **Settings > Actions > Runners > New self-hosted runner** を開く
2. macOS 用のダウンロードコマンドを実行
3. `./config.sh --url <repo_url> --token <token>` を実行
4. Mac再起動後も自動起動するよう launchd に登録:

```bash
./svc.sh install
./svc.sh start
```

### 使い方

`pending_urls.txt` に処理したいURLを追加してコミット＆プッシュするだけで、Runnerが自動起動します。結果は `output/` に保存され、`processed_urls.txt` とともに自動コミットされます。

手動実行:

```bash
python runner/run_and_commit.py
```

---

## テスト

```bash
# 単体・統合テスト（モックあり、CI環境でも実行可）
pytest tests/unit tests/integration

# カバレッジ付き
pytest tests/unit tests/integration \
  --cov=core --cov=cli --cov=watchdog_mode --cov=runner \
  --cov-report=term-missing
```

E2Eテスト（Apple Siliconのみ・手動実行）は [Issue #3](../../issues/3) を参照してください。

---

## ディレクトリ構成

```
.
├── core/               # 共通コアモジュール
│   ├── url_store.py    # URLリスト管理
│   ├── downloader.py   # yt-dlp ラッパー
│   ├── transcriber.py  # mlx-whisper ラッパー
│   ├── writer.py       # テキスト出力
│   └── pipeline.py     # オーケストレーター
├── cli/
│   └── run.py          # Phase 1 エントリーポイント
├── watchdog_mode/
│   └── watcher.py      # Phase 2 エントリーポイント
├── runner/
│   └── run_and_commit.py  # Phase 3 エントリーポイント
├── .github/workflows/
│   └── transcribe.yml  # GitHub Actions ワークフロー
├── tests/
│   ├── unit/           # 単体テスト
│   ├── integration/    # 統合テスト
│   ├── e2e/            # E2Eテスト（Apple Siliconのみ）
│   └── fixtures/
├── pending_urls.txt    # 処理待ちURLリスト
├── processed_urls.txt  # 処理済みURLリスト
└── output/             # 文字起こし結果
```

## エラーコード

| コード | 例外 | 対応 |
|--------|------|------|
| E001 | `VideoUnavailableError` | スキップして次のURLへ |
| E002 | `DownloadError` | 最大3回リトライ後にスキップ |
| E003 | `TranscriptionError` | スキップして次のURLへ |
| E004 | `WriteError` | 処理を中断（exit 1） |
| E005 | `StoreCorruptedError` | 処理を中断（exit 1） |
