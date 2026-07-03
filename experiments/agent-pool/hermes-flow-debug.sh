#!/usr/bin/env bash
# hermes-flow-debug — 按 run ID 导出完整调试信息
# Usage: hermes-flow-debug <run_id>

set -e

if [ -z "$1" ]; then
  echo "用法: hermes-flow-debug <run_id>"
  echo ""
  echo "示例:"
  echo "  hermes-flow-debug d2ddb02588f9"
  exit 1
fi

RID="$1"
PROJECT_ROOT="${HERMES_FLOW_PROJECT_ROOT:-$PWD}"

# Try state.sqlite then state.db
DB="$PROJECT_ROOT/.hermes-flow/runs/$RID/state.sqlite"
if [ ! -f "$DB" ]; then
  DB="$PROJECT_ROOT/.hermes-flow/runs/$RID/state.db"
fi

if [ ! -f "$DB" ]; then
  echo "❌ 找不到 run $RID 的数据库"
  echo "   路径: $PROJECT_ROOT/.hermes-flow/runs/$RID/"
  ls "$PROJECT_ROOT/.hermes-flow/runs/$RID/" 2>/dev/null || echo "   目录不存在"
  exit 1
fi

# Check if database has tables
TABLES=$(sqlite3 "$DB" ".tables" 2>/dev/null)
if [ -z "$TABLES" ]; then
  echo "⚠️  数据库为空（0 表）—— flow_init 可能失败或数据库不完整"
  ls -la "$DB"
  exit 0
fi

echo "╔══════════════════════════════════════════════╗"
echo "║  Hermes Flow Debug: $RID"
echo "╚══════════════════════════════════════════════╝"
echo ""

echo "📋 RUN"
echo "────────────────────────────────────────────────"
sqlite3 -header "$DB" "SELECT run_id, status, current_state_id, datetime(created_at) as created, datetime(updated_at) as updated FROM runs;"
echo ""

echo "📊 决策序列"
echo "────────────────────────────────────────────────"
sqlite3 -header "$DB" "SELECT rowid, state_id, role_id, value, datetime(created_at) as ts FROM decisions ORDER BY rowid;"
echo ""

echo "🔄 状态流转"
echo "────────────────────────────────────────────────"
sqlite3 -header "$DB" "SELECT rowid, from_state_id, to_state_id FROM transitions ORDER BY rowid;"
echo ""

echo "💬 消息"
echo "────────────────────────────────────────────────"
sqlite3 -header "$DB" "SELECT rowid, from_role, datetime(created_at) as ts, substr(content,1,120) as content FROM messages ORDER BY rowid;" 2>/dev/null || echo "  (无)"
echo ""

echo "⚙️  状态配置"
echo "────────────────────────────────────────────────"
sqlite3 -header "$DB" "SELECT state_id, json_extract(state_json, '\$.gate.type') as gate_type, json_extract(state_json, '\$.output_artifacts') as artifacts, json_extract(state_json, '\$.gate.on_pass') as on_pass, json_extract(state_json, '\$.gate.on_fail') as on_fail, json_extract(state_json, '\$.gate.max_rounds') as max_r FROM states ORDER BY rowid;" 2>/dev/null

echo ""
echo "⏱️  耗时"
ROW=$(sqlite3 "$DB" "SELECT datetime(created_at), datetime(updated_at) FROM runs;" 2>/dev/null)
if [ -n "$ROW" ]; then
  echo "  $ROW"
fi
