<p align="center">
  <img src="assets/logler-logo.png" width="200" alt="logler">
</p>

<h3 align="center">なぜ失敗したのかを、ログファイルから突き止める。人とAIエージェントのために。パーサーはRust製</h3>

<p align="center">
  <a href="https://pypi.org/project/logler/"><img src="https://img.shields.io/pypi/v/logler.svg?logo=pypi&logoColor=white" alt="PyPI"></a>
  <a href="https://opensource.org/licenses/MIT"><img src="https://img.shields.io/badge/License-MIT-green.svg" alt="MIT"></a>
  <a href="https://github.com/gabu-quest/logler/actions"><img src="https://img.shields.io/github/actions/workflow/status/gabu-quest/logler/ci.yml?logo=github&label=CI" alt="CI"></a>
</p>

<p align="center">
  <a href="README.md">English</a> | 日本語
</p>

---

logler は、何かがおかしくなった直後の調査のためのツールです。ログファイルをその場で読み、原因を突き止める手助けをします。どのリクエストが失敗したか、そのうちの1つが複数のサービスで何をしたか、成功したリクエストと何が違うか、時間がどこで使われたか。文字列を探すだけで構造を知らない `grep` と、サーバーが必要なログ基盤との間に位置します。何もアップロードせず、バックグラウンドで動くものもありません。

調査コマンドはすべて `logler llm` の下にJSON版があり、AIエージェントが呼び出すために作られています。同じエンジンをPythonライブラリとしても、ターミナルビューアとしても使えます。

## インストール

```bash
pip install logler
```

Python 3.12 以降が必要です。wheel にRust製パーサーが含まれるので、コンパイラは不要です。

## クイックスタート

次の5行を `app.log` として保存します。

```json
{"timestamp":"2026-11-14T10:00:00.000Z","level":"INFO","message":"request start","thread_id":"req-123","span_id":"a","service":"api"}
{"timestamp":"2026-11-14T10:00:00.050Z","level":"INFO","message":"auth ok","thread_id":"req-123","span_id":"b","parent_span_id":"a","service":"auth"}
{"timestamp":"2026-11-14T10:00:00.450Z","level":"ERROR","message":"Redis connection refused","thread_id":"req-123","span_id":"c","parent_span_id":"a","service":"cache"}
{"timestamp":"2026-11-14T10:00:00.520Z","level":"INFO","message":"request done","thread_id":"req-123","span_id":"a","service":"api"}
{"timestamp":"2026-11-14T10:00:01.000Z","level":"ERROR","message":"timeout talking to db","thread_id":"req-124","span_id":"d","service":"api"}
```

**エージェント向け**（JSON出力）:

```console
$ logler llm triage app.log
{"assessment": {"severity": "critical", "confidence": 0.95, "summary": "Error rate: 40.0%, 2 errors in 5 entries"}, ...}

$ logler llm search app.log --level ERROR --tail 5
$ logler llm hierarchy req-123 --files app.log
```

**人向け:**

```bash
logler view app.log --level ERROR    # 色付きのターミナル出力
logler stats app.log                 # レベルごとの件数
```

**Pythonから:**

```python
from logler.investigate import follow_thread_hierarchy, search

results = search(files=["app.log"], level="ERROR", limit=5)
for hit in results["results"]:
    print(f"[{hit['entry']['level']}] {hit['entry']['message']}")
# [ERROR] Redis connection refused
# [ERROR] timeout talking to db

tree = follow_thread_hierarchy(files=["app.log"], root_identifier="req-123")
```

## 調査の進め方

| | 問い | 答えるもの |
|---|---|---|
| 1 | どれくらい深刻か、いつからか | `triage`、`summarize` |
| 2 | どのリクエストが失敗したか | `search --level ERROR`、`ids` |
| 3 | 失敗したリクエストは何をしたか、時間はどこで使われたか | `hierarchy`、`bottleneck`、複数サービスのファイルにまたがる `correlate` |
| 4 | エラーはどう伝わったか | `analyze_error_flow()`: あるエラーから、それが伝わった経路と影響を受けたスパンをたどる |
| 5 | 成功したリクエストや昨日と何が違うか | 2つのリクエストまたは2つの期間を比べる `compare`、`diff` |
| 6 | 証拠は疑っている原因と合うか | `verify-pattern`、`metrics`、`sql` |
| 7 | 何が分かったか | `session note`、`session conclude`: メモとレポートを付けて保存できる調査 |

手順3から5はIDをたどるため、ログ行にリクエスト、スレッド、トレース、スパンのいずれかのIDが必要です。IDがなくても、手順1、2、6は使えます。

ほかに: 大きなファイルからの代表的なサンプル（`sample`）、フォーマットの判定と繰り返し現れるメッセージのテンプレート抽出（`detect`、`templates`）、トレースの Jaeger または Zipkin へのエクスポート（`export`）。

設定なしで読めるフォーマット: JSON（最も確実）、syslog（RFC 3164 と 5424）、logfmt、Apache common log format、プレーンテキスト。独自のフォーマットは `.logler/formats.yaml` に正規表現で書きます（[docs/CONFIGURATION.md](docs/CONFIGURATION.md)）。

クイックスタートのファイルにある `req-123` のリクエストツリーを `format_tree()` で表示すると次のようになります。

```
└── request start (2 entries, 520ms)
    ├── auth ok (1 entries, <1ms)
    └── ❌ [1 errors] Redis connection refused (1 entries, <1ms)
```

## エージェント向けコマンド

すべて `logler llm` の下にあり、すべてJSONを出力します。終了コード 0 は結果あり、1 は結果なし、2 は呼び出し側の誤り（不正な引数、読めないファイル）、3 は内部エラーです。

| 目的 | コマンド |
|---|---|
| 最初の確認 | `triage`, `summarize`, `schema` |
| 検索 | `search`, `ids`, `sample`, `sql` |
| トレース | `correlate`, `hierarchy`, `bottleneck`, `context`, `export` |
| 比較 | `compare`, `diff` |
| セッション | `session create/list/query/note/conclude` |
| フォーマット | `detect`, `format list/test/validate`, `templates` |
| 相関 | `correlation list/run`, `correlate-events` |
| メトリクスと検証 | `metrics`, `verify-pattern`, `emit` |

ログファイルを読むコマンドは、`context` と `format test` を除いてすべて `--db path/to/app.db` も受け取り、[sqler](https://github.com/gabu-quest/sqler) データベースに保存されたログレコードを読みます。[qler](https://github.com/gabu-quest/qler) の `qler logs` は、この仕組みでジョブのログ行を表示します。

完全なリファレンス: [docs/LLM_CLI_REFERENCE.md](docs/LLM_CLI_REFERENCE.md)

## 使いどころ

向いている場面: 証拠がディスク上のログファイルにあるインシデントの原因調査。ログを調査する必要があるエージェント。1つのリクエストを複数サービスのファイルにまたがって追う作業。失敗したケースと成功したケースの比較。

ターミナルでログをリアルタイムに眺めたいとき（gonzo、lnav）、ログを保存して集計したいとき（Loki、ELK、Datadog）、リアルタイムでアラートを出したいとき（Prometheus と Alertmanager）、テキストを検索するだけのとき（ripgrep）は、別のツールを使ってください。

## インタラクティブツアー

サンプルデータ付きの [marimo](https://marimo.io) ノートブックが17本あります。**[ブラウザで開く](https://gabu-quest.github.io/logler/)**か、`uv run marimo edit examples/tours/tour_01_fundamentals.py` でローカルで実行できます。

| ツアー | 内容 |
|------|--------|
| 01. Fundamentals | 検索、フィルタ、出力形式 |
| 02. Thread Tracking | グループ化、相関ID |
| 03. Hierarchy | ツリー表示、ウォーターフォール、ボトルネック |
| 04. Investigation | セッション、履歴、レポート |
| 05. Pattern Detection | 繰り返しパターン、頻度 |
| 06. Flamegraph | 時間がどこで使われたか |
| 07. Error Flow | 根本原因、伝播 |
| 08. Comparison | ツリーの差分、スレッドの比較 |
| 09. Tracing Exports | Jaeger 形式と Zipkin 形式 |
| 10. Sampling | サンプリング戦略 |
| 11. AI Insights | エージェントによる調査を1ステップずつ |
| 12. Multi-File | 複数サービスにまたがる1つのリクエスト |
| 13. Live Watching | 末尾の追跡（tail） |
| 14. Performance | 大きなファイル |
| 15. Filtering | フィールドフィルタ、複雑なクエリ |
| 16. Metrics | 数値、統計、外れ値 |
| 17. Format Detection | フォーマットとテンプレート |

## ドキュメント

ドキュメントは英語です。

| | |
|---|---|
| [APIリファレンス](docs/API.md) | Python API と、テストで確認している契約 |
| [エージェント向けコマンドリファレンス](docs/LLM_CLI_REFERENCE.md) | `logler llm` の全コマンドと全フラグ |
| [Pythonガイド](docs/LLM_README.md) | ライブラリとしての使い方 |
| [設定](docs/CONFIGURATION.md) | 独自のログフォーマットと相関ルール |
| [タイムスタンプ](docs/TIMESTAMPS.md) | 読み取れる時刻の書き方と、タイムゾーンの決め方 |
| [リクエストツリー](docs/HIERARCHY_GUIDE.md) | リクエストのスパンをどう見つけ、どう表示するか |
| [変更履歴](CHANGELOG.md) | 変更点と、アップグレード時に直す箇所 |
| [Web UI](https://github.com/gabu-quest/logler-web) | ブラウザ用インターフェース（別リポジトリ） |

## -ler ファミリー

| パッケージ | 概要 |
|---|---|
| [sqler](https://github.com/gabu-quest/sqler) | SQLite に保存するJSONドキュメント |
| [qler](https://github.com/gabu-quest/qler) | sqler の上に作られたバックグラウンドジョブキュー |
| **logler** | このパッケージ。`--db` で sqler データベースのログレコードを読む |

## 開発

```bash
uv sync --extra dev            # Rust拡張をビルドし、開発ツールをインストールする
uv run pytest
cargo test --workspace
uv sync --extra dev --reinstall-package logler   # Rustコードを変更した後
```

## ライセンス

MIT。[LICENSE](LICENSE) を参照してください。
