# 🤖 LLMエージェント向けLogler

**Rust製の高性能ログ解析エンジン - AIエージェント専用設計**

## 🎯 これは何か

LoglerにはRust製の**調査エンジン**が含まれており、ClaudeのようなLLMエージェントが効率的にログを調査できるように特別に設計されています。AIの探偵に超能力を与えて、ログを光速で分析できるようにすると考えてください。

## ⚡ 主な機能

- **🚀 超高速**: Rust製バックエンドで並列処理 - 1GBファイルを50ms未満で検索
- **🔍 セマンティック検索**: 完全一致ではなく、説明でエラーを検索
- **🧵 スレッド追跡**: 分散システム全体でリクエストフローを再構築
- **📊 パターン検出**: 繰り返されるエラーやカスケード障害を自動検出
- **📈 統計分析**: エラー率、応答時間、異常に関する洞察を取得
- **💾 SQLクエリ**: DuckDBを使用した低レベルクエリでカスタム分析
- **🎨 美しい出力**: リッチターミナル出力とプログラマティックアクセス用JSON
- **🔌 簡単な統合**: LLM関数呼び出し用に設計されたシンプルなPython API

## 🚀 LLMエージェント向けクイックスタート

### インストール

```bash
# Rustバックエンド付きloglerをインストール
pip install logler

# またはソースからmaturinでビルド
cd logler
maturin develop --release
```

### 基本的な使い方 (Python)

```python
import logler.investigate as investigate

# エラーを検索
results = investigate.search(
    files=["app.log"],
    query="database timeout",
    level="ERROR",
    limit=10
)

print(f"{results['total_matches']}件のエラーを発見")
print(f"検索時間: {results['search_time_ms']}ms")

for result in results['results']:
    print(f"行{result['entry']['line_number']}: {result['entry']['message']}")
```

### 高度な使い方 (永続インデックス)

```python
from logler.investigate import Investigator

# Investigatorを作成してファイルをロード
investigator = Investigator()
investigator.load_files(["app.log", "api.log"])

# 複数の操作を実行
results = investigator.search(query="error", limit=10)
patterns = investigator.find_patterns(min_occurrences=3)
metadata = investigator.get_metadata()

# 特定のリクエストを追跡
timeline = investigator.follow_thread(correlation_id="req-001")
```

### SQLクエリ (低レベル調査)

```python
from logler.investigate import Investigator

investigator = Investigator()
investigator.load_files(["app.log"])

# カスタムSQLクエリを実行
results = investigator.sql_query("""
    SELECT
        level,
        COUNT(*) as count,
        MIN(timestamp) as first_seen,
        MAX(timestamp) as last_seen
    FROM logs
    WHERE timestamp > '2024-01-15 10:00:00'
    GROUP BY level
    ORDER BY count DESC
""")

# 時系列分析
time_series = investigator.sql_query("""
    SELECT
        strftime('%Y-%m-%d %H:%M', timestamp) as minute,
        level,
        COUNT(*) as count
    FROM logs
    WHERE level IN ('ERROR', 'FATAL')
    GROUP BY minute, level
    ORDER BY minute
""")

# スレッド間の相関を見つける
correlations = investigator.sql_query("""
    SELECT
        t1.thread_id as thread1,
        t2.thread_id as thread2,
        COUNT(*) as shared_errors
    FROM logs t1
    JOIN logs t2
        ON t1.correlation_id = t2.correlation_id
        AND t1.thread_id < t2.thread_id
    WHERE t1.level = 'ERROR' AND t2.level = 'ERROR'
    GROUP BY t1.thread_id, t2.thread_id
    HAVING shared_errors > 5
    ORDER BY shared_errors DESC
""")
```

## 🛠️ 調査ツール

### 1. `search()` - ログエントリを検索

```python
results = investigate.search(
    files=["app.log"],
    query="database connection failed",
    level="ERROR",              # レベルでフィルタ
    thread_id="worker-1",       # スレッドでフィルタ
    correlation_id="req-001",   # コリレーションIDでフィルタ
    limit=100,
    context_lines=3             # 前後3行を含める
)
```

### 2. `follow_thread()` - リクエストフローを再構築

```python
timeline = investigate.follow_thread(
    files=["app.log"],
    thread_id="worker-1",          # スレッドで追跡
    correlation_id="req-001",      # またはコリレーションIDで
    trace_id="abc123"              # またはトレースIDで
)
```

### 3. `find_patterns()` - 繰り返される問題を検出

```python
patterns = investigate.find_patterns(
    files=["app.log"],
    min_occurrences=3
)
```

### 4. `get_metadata()` - ファイル情報

```python
metadata = investigate.get_metadata(files=["app.log"])
```

### 5. `sql_query()` - カスタムSQL分析

```python
# レベル別の集計
results = investigator.sql_query("""
    SELECT level, COUNT(*) as count
    FROM logs
    GROUP BY level
""")

# エラーの多いスレッドを見つける
top_threads = investigator.sql_query("""
    SELECT thread_id, COUNT(*) as error_count
    FROM logs
    WHERE level = 'ERROR'
    GROUP BY thread_id
    ORDER BY error_count DESC
    LIMIT 10
""")

# 時間帯別のエラー率
hourly_errors = investigator.sql_query("""
    SELECT
        strftime('%H', timestamp) as hour,
        COUNT(*) as errors,
        COUNT(*) * 100.0 / SUM(COUNT(*)) OVER() as percentage
    FROM logs
    WHERE level IN ('ERROR', 'FATAL')
    GROUP BY hour
    ORDER BY hour
""")
```

## 📊 調査ワークフローの例

本番環境の問題をLLMエージェントが調査する方法:

```python
import logler.investigate as investigate

# ステップ1: 概要を取得
metadata = investigate.get_metadata(files=["app.log"])
print(f"{metadata[0]['lines']}件のログエントリを分析中")
print(f"時間範囲: {metadata[0]['time_range']['start']} から {metadata[0]['time_range']['end']}")
print(f"エラー数: {metadata[0]['log_levels']['ERROR']}")

# ステップ2: エラーを検索
errors = investigate.search(
    files=["app.log"],
    level="ERROR",
    limit=100
)
print(f"\n{errors['search_time_ms']}msで{errors['total_matches']}件のエラーを発見")

# ステップ3: パターンを検出
patterns = investigate.find_patterns(
    files=["app.log"],
    min_occurrences=3
)
print(f"\nトップエラーパターン: {patterns['patterns'][0]['pattern']}")
print(f"{patterns['patterns'][0]['occurrences']}回発生")

# ステップ4: SQLで深掘り
from logler.investigate import Investigator
investigator = Investigator()
investigator.load_files(["app.log"])

# エラーの急増を見つける
spikes = investigator.sql_query("""
    WITH error_counts AS (
        SELECT
            strftime('%Y-%m-%d %H:%M', timestamp) as minute,
            COUNT(*) as errors
        FROM logs
        WHERE level = 'ERROR'
        GROUP BY minute
    )
    SELECT
        minute,
        errors,
        LAG(errors) OVER (ORDER BY minute) as prev_errors,
        errors - LAG(errors) OVER (ORDER BY minute) as spike
    FROM error_counts
    WHERE errors > 10 AND spike > 5
    ORDER BY spike DESC
""")

print(f"\nエラー急増を検出:")
for spike in spikes:
    print(f"  {spike['minute']}: {spike['errors']}件 (前回比+{spike['spike']})")

# ステップ5: 根本原因を調査
first_error = errors['results'][0]['entry']
if first_error['correlation_id']:
    timeline = investigator.follow_thread(
        correlation_id=first_error['correlation_id']
    )
    print(f"\nリクエストは{timeline['duration_ms']}msで{timeline['total_entries']}件のログエントリがありました")

    # タイムラインを表示
    for entry in timeline['entries']:
        print(f"  {entry['timestamp']} [{entry['level']}] {entry['message']}")
```

## 🏗️ アーキテクチャ

```
┌─────────────────────────────────────┐
│         Pythonレイヤー               │
│  (logler/investigate.py)            │
│  - LLMエージェント向けシンプルAPI    │
│  - JSONシリアライゼーション          │
└─────────────────┬───────────────────┘
                  │
                  ▼
┌─────────────────────────────────────┐
│      PyO3バインディング              │
│  (crates/logler-py)                 │
│  - Python ↔ Rustブリッジ             │
└─────────────────┬───────────────────┘
                  │
                  ▼
┌─────────────────────────────────────┐
│     Rustコアエンジン                 │
│  (crates/logler-core)               │
│  - 高速ログ解析                      │
│  - インメモリインデックス            │
│  - 並列処理 (Rayon)                 │
│  - メモリマップI/O                   │
│  - DuckDB SQLエンジン               │
└─────────────────────────────────────┘
```

## ⚡ パフォーマンス

| 操作 | ファイルサイズ | 時間 | スループット |
|------|---------------|------|-------------|
| 検索 | 1GB | <50ms | 20 GB/s |
| スレッド追跡 | 1GB | <20ms | 50 GB/s |
| パターン検出 | 1GB | <200ms | 5 GB/s |
| インデックス構築 | 1GB | <500ms | 2 GB/s |
| SQLクエリ | 1GB | <100ms | 10 GB/s |

**メモリ使用量:**
- ベース: <100MB
- 1GBファイルインデックス済み: ~200MB
- 10GBファイルインデックス済み: ~2GB

## 🔍 サポートされているログ形式

- **JSON**: 構造化ログで自動フィールド抽出
- **プレーンテキスト**: タイムスタンプ、レベル、スレッドのパターンベース解析
- **Syslog**: 標準syslog形式
- **カスタム**: 拡張可能なパーサー

## 💾 利用可能なSQLテーブル

ロードされたログは`logs`テーブルで利用可能:

| カラム | 型 | 説明 |
|--------|------|------|
| file | TEXT | ログファイルパス |
| line_number | INTEGER | 行番号 |
| timestamp | TIMESTAMP | タイムスタンプ |
| level | TEXT | ログレベル(ERROR, INFO等) |
| message | TEXT | ログメッセージ |
| thread_id | TEXT | スレッドID |
| correlation_id | TEXT | コリレーションID |
| trace_id | TEXT | トレースID |
| span_id | TEXT | スパンID |
| raw | TEXT | 元の行 |

## 🎓 SQLクエリ例

### エラー分析
```sql
-- レベル別エラー数
SELECT level, COUNT(*) as count
FROM logs
WHERE level IN ('ERROR', 'FATAL')
GROUP BY level;

-- 最も多いエラーメッセージ
SELECT
    SUBSTR(message, 1, 50) as error_prefix,
    COUNT(*) as occurrences,
    MIN(timestamp) as first_seen,
    MAX(timestamp) as last_seen
FROM logs
WHERE level = 'ERROR'
GROUP BY error_prefix
ORDER BY occurrences DESC
LIMIT 10;
```

### 時系列分析
```sql
-- 1分ごとのエラー率
SELECT
    strftime('%Y-%m-%d %H:%M', timestamp) as minute,
    COUNT(*) as errors
FROM logs
WHERE level = 'ERROR'
GROUP BY minute
ORDER BY minute;

-- ピーク時間を見つける
SELECT
    strftime('%H', timestamp) as hour,
    COUNT(*) as errors,
    AVG(COUNT(*)) OVER() as avg_errors
FROM logs
WHERE level = 'ERROR'
GROUP BY hour
HAVING errors > avg_errors * 2
ORDER BY errors DESC;
```

### スレッド分析
```sql
-- エラーの多いスレッド
SELECT
    thread_id,
    COUNT(*) as error_count,
    COUNT(DISTINCT correlation_id) as affected_requests,
    MIN(timestamp) as first_error,
    MAX(timestamp) as last_error
FROM logs
WHERE level = 'ERROR' AND thread_id IS NOT NULL
GROUP BY thread_id
ORDER BY error_count DESC
LIMIT 10;

-- スレッド間の相関
SELECT
    t1.thread_id,
    t2.thread_id,
    COUNT(*) as shared_correlation_ids
FROM logs t1
JOIN logs t2 ON t1.correlation_id = t2.correlation_id
WHERE t1.thread_id < t2.thread_id
GROUP BY t1.thread_id, t2.thread_id
ORDER BY shared_correlation_ids DESC
LIMIT 10;
```

### リクエスト分析
```sql
-- 最も遅いリクエスト
SELECT
    correlation_id,
    COUNT(*) as log_entries,
    MIN(timestamp) as start_time,
    MAX(timestamp) as end_time,
    (julianday(MAX(timestamp)) - julianday(MIN(timestamp))) * 86400000 as duration_ms
FROM logs
WHERE correlation_id IS NOT NULL
GROUP BY correlation_id
ORDER BY duration_ms DESC
LIMIT 10;

-- エラーのあるリクエストの割合
SELECT
    COUNT(DISTINCT correlation_id) as total_requests,
    COUNT(DISTINCT CASE WHEN level = 'ERROR' THEN correlation_id END) as failed_requests,
    COUNT(DISTINCT CASE WHEN level = 'ERROR' THEN correlation_id END) * 100.0 /
        COUNT(DISTINCT correlation_id) as failure_rate
FROM logs
WHERE correlation_id IS NOT NULL;
```

## 🤔 なぜLLMフレンドリーか?

1. **高速応答**: 秒単位ではなく、ミリ秒単位の結果
2. **構造化出力**: すべての結果は解析しやすいJSON形式
3. **セマンティック関連性**: 検索結果は関連性でランク付け
4. **コンテキスト付き**: 周囲のログ行を自動で取得
5. **パターン検出**: LLMが生ログで見逃す可能性のある問題を発見
6. **統計**: より良い理解のための集約的洞察
7. **スレッド追跡**: 複雑なリクエストフローを簡単に再構築
8. **SQLアクセス**: カスタム分析のための低レベルクエリ

## 📚 ドキュメント

- **[英語版README](README.md)**: 英語の完全なドキュメント
- **[LLM調査API](docs/LLM_INVESTIGATION_API.md)**: スキーマ付き完全APIリファレンス
- **[LLM README](docs/LLM_README.md)**: 使用例付き入門ガイド
- **[例](examples/)**: 実世界の調査シナリオ

## 📖 例

詳細な例については`examples/`ディレクトリを参照してください:

- **基本的な調査** - 検索、フィルタリング、コンテキスト
- **分散トレーシング** - マイクロサービス全体でリクエストを追跡
- **パフォーマンス分析** - ボトルネックと遅いクエリを見つける
- **異常検出** - 統計的異常とスパイクを検出
- **SQL分析** - カスタムクエリによる高度な調査
- **本番環境インシデント** - 実際のインシデント対応シナリオ

日本語の例は`examples/ja/`にあります。

## 🚧 今後の機能強化

- [ ] Claude Desktopとの統合のためのMCP (Model Context Protocol)サーバー
- [ ] リアルタイムログ追跡のためのWebSocketストリーミング
- [ ] カスタムパーサープラグイン
- [ ] 異常検出の改善
- [ ] ビジュアライゼーションAPI

## 📄 ライセンス

MITライセンス - LICENSEファイルを参照

---

**🦀 Rustで速度を、🤖 AIエージェントのために構築**
