# ytb-transcription-pipeline

YouTube 音声や動画の文字起こしを処理するパイプラインです。  
A pipeline for transcribing YouTube audio and video into usable text.

## 概要

この README は、このリポジトリの役割を示すための最小 README です。
詳細な使い方、設計、運用ルールが必要な場合は今後追加します。

## 用語としての用例・思想的背景

「処理待ちURLを文字起こしパイプラインへ渡し、後から読めるテキストを残す」という用途を想定します。URLの取得、音声ダウンロード、認識、保存を共通コアに分け、CLI・ファイル監視・runnerの各入口から再利用する設計です。許可を得たコンテンツを対象にし、認識結果は原音と照合してください。

## 技術的背景

[core/](core/) にURL管理、yt-dlpによるダウンロード、mlx-whisperによる認識、出力保存を分離しています。[実装仕様](docs/spec.md) はApple SiliconのmacOS、Python 3.11以降、ffmpeg等を前提としています。実際に導入する際は [requirements.txt](requirements.txt) と対象環境の互換性を確認してください。

## 実行の入口

- [CLI](cli/run.py): python -m cli.run --dry-run で未処理件数を確認し、python -m cli.run で処理します。既定の入力は pending_urls.txt、処理済み管理は processed_urls.txt、出力先は output/ です。
- [ファイル監視](watchdog_mode/watcher.py): 継続監視の入口です。稼働させる環境を別途用意します。
- [runner](runner/run_and_commit.py) と [workflow](.github/workflows/transcribe.yml): self-hosted runnerで実行し、結果をcommit / pushする構成です。runnerの設定や権限が必要で、ファイルがあることだけで稼働済みとは判断できません。

## 歴史的背景

[2026年4月のPR #4](https://github.com/masa-san-jp/ytb-transcription-pipeline/pull/4) までに、CLI・監視・runnerの利用説明を含む開発が取り込まれ、同年5月12日に最小READMEが追加されています。仕様書の更新日表記とコミット時刻は別の記録として扱います。

## 展開と検証の境界

最初はCLIの件数確認と少数の許可済みURLで入出力を確かめ、その後に監視やrunnerの運用を検討してください。workflowは pending_urls.txt のpushまたは手動実行が入口で、README更新だけを対象にしたテストCIではありません。リポジトリには [単体・統合テスト](tests/) がありますが、このREADME整備ではモデルのダウンロード、動画取得、実機文字起こし、runner登録は行っていません。
