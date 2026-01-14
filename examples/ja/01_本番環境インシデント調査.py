"""
本番環境インシデント調査 - データベース接続プール枯渇

この例は、本番環境サービスがデータベース接続プール枯渇により
カスケード障害を経験する実際のシナリオを示しています。

シナリオ:
- 14:55:00にサービスが正常に開始
- データベース接続プールが飽和し始める（18/20接続）
- 14:55:02にタイムアウトが複数のワーカーにカスケード
- エラー率が85%に急上昇
- 運用チームがインシデントを検出し、接続プールをスケール
- 遅いクエリを強制終了
- 14:55:08までにサービスが回復

学習目標:
- search()を使用してエラーパターンを見つける
- follow_thread()を使用してリクエストタイムラインを再構築
- find_patterns()を使用してカスケード障害を検出
- SQLクエリを使用した時系列分析
- 根本原因と解決タイムラインを特定
"""

import logler.investigate as investigate
from logler.investigate import Investigator

LOG_FILE = "examples/logs/production_incident.log"

print("=" * 80)
print("本番環境インシデント調査")
print("=" * 80)
print()

# ステップ1: インシデントの概要を取得
print("📊 ステップ1: インシデント概要の取得...")
print("-" * 80)

metadata = investigate.get_metadata([LOG_FILE])
file_meta = metadata[0]

print(f"📝 ログファイル: {file_meta['path']}")
print(f"📏 総エントリ数: {file_meta['lines']}")
print(f"⏰ 時間範囲: {file_meta['time_range']['start']} から {file_meta['time_range']['end']}")
print(f"🧵 ユニークスレッド数: {file_meta['unique_threads']}")
print(f"🔗 コリレーションID数: {file_meta['unique_correlation_ids']}")
print()
print("ログレベル:")
for level, count in sorted(file_meta["log_levels"].items(), key=lambda x: x[1], reverse=True):
    print(f"  {level:10s}: {count:3d} エントリ")
print()

# ステップ2: すべてのエラーを検索
print("🔍 ステップ2: エラーの検索...")
print("-" * 80)

errors = investigate.search(files=[LOG_FILE], level="ERROR", limit=100)

print(f"⚠️  {errors['search_time_ms']}msで{errors['total_matches']}件のERRORエントリを発見")
print()

# 最初のエラーをいくつか表示
print("最初の5件のエラー:")
for i, result in enumerate(errors["results"][:5], 1):
    entry = result["entry"]
    print(f"  {i}. [{entry['timestamp']}] {entry['thread_id']}: {entry['message']}")
print()

# ステップ3: エラーパターンの検出
print("🔎 ステップ3: エラーパターンの検出...")
print("-" * 80)

patterns = investigate.find_patterns(files=[LOG_FILE], min_occurrences=2)

print(f"📈 {len(patterns['patterns'])}件のエラーパターンを発見:")
for i, pattern in enumerate(patterns["patterns"], 1):
    print(f"\n  パターン{i}:")
    print(f"    メッセージ: {pattern['pattern']}")
    print(f"    発生回数: {pattern['occurrences']}")
    print(f"    初回発生: {pattern['first_seen']}")
    print(f"    最終発生: {pattern['last_seen']}")
    print(f"    影響を受けたスレッド: {', '.join(pattern['affected_threads'][:5])}")
    if len(pattern["affected_threads"]) > 5:
        print(f"    ... 他{len(pattern['affected_threads']) - 5}スレッド")
print()

# ステップ4: 失敗したリクエストの調査
print("🧵 ステップ4: 失敗したリクエストのタイムライン追跡...")
print("-" * 80)

# エラーが発生したリクエストを見つける
first_error = errors["results"][0]["entry"]
correlation_id = first_error.get("correlation_id")

if correlation_id:
    print(f"📍 リクエストを追跡中: {correlation_id}")
    print()

    timeline = investigate.follow_thread(files=[LOG_FILE], correlation_id=correlation_id)

    print(f"🕐 リクエスト所要時間: {timeline['duration_ms']}ms")
    print(f"📝 ログエントリ数: {timeline['total_entries']}")
    print(f"🔗 スパン数: {len(timeline['unique_spans'])}")
    print()
    print("タイムライン:")
    for entry in timeline["entries"]:
        level_emoji = {"INFO": "ℹ️", "WARN": "⚠️", "ERROR": "❌", "FATAL": "💀"}.get(
            entry["level"], "📝"
        )
        print(f"  {level_emoji} [{entry['timestamp']}] {entry['message'][:70]}")
print()

# ステップ5: SQL分析 - エラーの時系列
print("📊 ステップ5: SQLを使用した時系列分析...")
print("-" * 80)

investigator = Investigator()
investigator.load_files([LOG_FILE])

# 時間ごとのエラー率を取得（秒単位）
print("秒ごとのエラー率を分析中...")
try:
    time_series = investigator.sql_query(
        """
        SELECT
            strftime('%H:%M:%S', timestamp) as second,
            level,
            COUNT(*) as count
        FROM logs
        WHERE level IN ('ERROR', 'FATAL', 'CRITICAL')
        GROUP BY second, level
        ORDER BY second
    """
    )

    print("\n⏱️  エラータイムライン（秒単位）:")
    for row in time_series:
        bar = "█" * min(row["count"], 50)
        print(f"  {row['second']} [{row['level']:8s}] {bar} {row['count']}")
    print()
except Exception as e:
    print(f"⚠️  SQL機能が利用できません: {e}")
    print("  （--features sql でビルドすると有効になります）")
    print()

# ステップ6: SQL分析 - 最も影響を受けたスレッド
print("🧵 ステップ6: 最も影響を受けたスレッドの特定...")
print("-" * 80)

try:
    affected_threads = investigator.sql_query(
        """
        SELECT
            thread_id,
            COUNT(CASE WHEN level IN ('ERROR', 'FATAL') THEN 1 END) as errors,
            COUNT(*) as total_logs,
            COUNT(CASE WHEN level IN ('ERROR', 'FATAL') THEN 1 END) * 100.0 /
                COUNT(*) as error_rate
        FROM logs
        WHERE thread_id IS NOT NULL AND thread_id NOT LIKE '%health%' AND thread_id NOT LIKE '%ops%'
        GROUP BY thread_id
        HAVING errors > 0
        ORDER BY errors DESC
        LIMIT 10
    """
    )

    print("エラー数トップ10スレッド:")
    for i, row in enumerate(affected_threads, 1):
        print(
            f"  {i:2d}. {row['thread_id']:12s}: {int(row['errors']):2d} エラー / {int(row['total_logs']):2d} 総数 (エラー率{row['error_rate']:.0f}%)"
        )
    print()
except Exception as e:
    print(f"⚠️  SQL機能が利用できません: {e}")
    print()

# ステップ7: 解決方法の発見
print("✅ ステップ7: インシデント解決の確認...")
print("-" * 80)

resolution = investigate.search(files=[LOG_FILE], query="resolved", limit=10)

if resolution["results"]:
    for result in resolution["results"]:
        entry = result["entry"]
        print(f"🎯 解決が{entry['timestamp']}に確認されました:")
        print(f"   スレッド: {entry['thread_id']}")
        print(f"   メッセージ: {entry['message']}")
        print()

# ステップ8: 根本原因の特定
print("🔬 ステップ8: 根本原因分析...")
print("-" * 80)

print("接続プールの警告を検索中...")
pool_warnings = investigate.search(files=[LOG_FILE], query="connection pool", limit=10)

for result in pool_warnings["results"]:
    entry = result["entry"]
    if entry["level"] == "WARN":
        print(f"⚠️  [{entry['timestamp']}] {entry['message']}")

print()

# まとめ
print("=" * 80)
print("📋 調査結果サマリー")
print("=" * 80)
print()
print("🔍 根本原因:")
print("   データベース接続プールの枯渇（20接続中18接続が使用中）")
print("   遅いクエリが接続をブロックし、タイムアウトのカスケードを引き起こした")
print()
print("📈 影響:")
print(f"   - {errors['total_matches']}件のリクエスト失敗")
print("   - エラー率は最大85%まで上昇")
print(
    f"   - {len(set(e['entry']['thread_id'] for e in errors['results']))}個のワーカースレッドが影響を受けた"
)
print()
print("✅ 解決策:")
print("   1. 接続プールを20から50接続にスケール")
print("   2. 実行中の遅いクエリ3件を強制終了")
print("   3. 約2.2秒でサービスが回復")
print()
print("💡 推奨事項:")
print("   - 接続プール使用率をプロアクティブに監視")
print("   - より厳格なクエリタイムアウト制限を設定")
print("   - 遅いクエリの自動終了を実装")
print("   - 接続プール飽和度80%超でのアラートを追加")
print()

print("=" * 80)
print("調査完了！✨")
print("=" * 80)
