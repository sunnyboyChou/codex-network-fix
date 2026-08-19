#!/bin/bash
# ============================================================
# pi-channel-check.sh — pi 模型通道健康检测 + 交互修复
# 检测 gpt-5.6-sol 是否走订阅 relay（openai-codex），而非 apiKey
# 用法:
#   ./pi-channel-check.sh          # 只检测
#   ./pi-channel-check.sh --fix    # 检测 + 交互修复
#   ./pi-channel-check.sh --auto   # 检测 + 自动修复（无交互）
# ============================================================
set -uo pipefail

SETTINGS="$HOME/.pi/agent/settings.json"
MODELS="$HOME/.pi/agent/models.json"
AUTH="$HOME/.pi/agent/auth.json"
RELAY_LOG="$HOME/tools/codex-relay/relay.log"
RELAY_LABEL="com.didi.codex-relay"
RELAY_SCRIPT="$HOME/tools/codex-relay/relay.sh"
SESSIONS_DIR="$HOME/.pi/agent/sessions"
PROXY_PORT=7897

MODE="${1:-check}"   # check | --fix | --auto
declare -a ISSUES=()      # 问题描述（红色）
declare -a WARNINGS=()    # 警告（黄色）

# ---- 颜色 ----
RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[0;33m'; CYAN='\033[0;36m'; NC='\033[0m'
ok()   { echo -e "  ${GREEN}✅${NC} $1"; }
warn() { echo -e "  ${YELLOW}⚠️ ${NC} $1"; }
fail() { echo -e "  ${RED}❌${NC} $1"; }
info() { echo -e "  ${CYAN}ℹ️ $1${NC}"; }

echo "=============================================="
echo " pi 模型通道健康检测 (gpt-5.6-sol → 订阅 relay)"
echo "=============================================="

# ---------- 1. settings.json 通道配置 ----------
echo -e "\n[1/6] settings.json 通道配置"
DP=$(python3 -c "import json;print(json.load(open('$SETTINGS')).get('defaultProvider',''))" 2>/dev/null)
DM=$(python3 -c "import json;print(json.load(open('$SETTINGS')).get('defaultModel',''))" 2>/dev/null)
TP=$(python3 -c "import json;print(json.load(open('$SETTINGS')).get('transport',''))" 2>/dev/null)
if [[ "$DP" == "openai-codex" ]]; then
  ok "defaultProvider = openai-codex"
else
  fail "defaultProvider = '${DP:-空}'（应为 openai-codex → 否则走 apiKey 429）"
  ISSUES+=("settings.json: defaultProvider=$DP")
fi
[[ "$DM" == "gpt-5.6-sol" ]] && ok "defaultModel = gpt-5.6-sol" || { warn "defaultModel = '${DM:-空}'（当前会话模型，可接受）"; WARNINGS+=("defaultModel=$DM"); }
if [[ "$TP" == "sse" ]]; then
  ok "transport = sse"
else
  fail "transport = '${TP:-空}'（应为 sse，否则 websocket 被 Cloudflare 拦）"
  ISSUES+=("settings.json: transport=$TP")
fi

# ---------- 2. models.json 指向本地 relay ----------
echo -e "\n[2/6] models.json relay 指向"
MU=$(python3 -c "import json;print(json.load(open('$MODELS')).get('providers',{}).get('openai-codex',{}).get('baseUrl',''))" 2>/dev/null)
if [[ "$MU" == "http://127.0.0.1:8899" ]]; then
  ok "openai-codex baseUrl → $MU"
else
  fail "baseUrl = '${MU:-空}'（应为 http://127.0.0.1:8899）"
  ISSUES+=("models.json: baseUrl=$MU")
fi

# ---------- 3. auth.json 凭据类型 ----------
echo -e "\n[3/6] auth.json 凭据"
AT=$(python3 -c "import json;print(json.load(open('$AUTH')).get('openai-codex',{}).get('type',''))" 2>/dev/null)
if [[ "$AT" == "oauth" ]]; then
  ok "openai-codex = oauth（订阅凭据）"
else
  fail "openai-codex type = '${AT:-空}'（应为 oauth；api_key 说明没配订阅）"
  ISSUES+=("auth.json: openai-codex type=$AT")
fi

# ---------- 4. relay 服务 ----------
echo -e "\n[4/6] codex-relay 服务 (port 8899)"
PID=$(launchctl list 2>/dev/null | awk -v l="$RELAY_LABEL" '$3==l {print $1}')
if [[ -n "$PID" && "$PID" != "-" ]]; then
  ok "relay 运行中 (PID $PID)"
else
  fail "relay 未运行（launchctl 无 ${RELAY_LABEL}）"
  ISSUES+=("relay 未运行")
fi
if [[ -f "$RELAY_LOG" ]]; then
  LAST_TS=$(stat -f "%m" "$RELAY_LOG" 2>/dev/null)
  NOW=$(date +%s)
  AGE=$(( (NOW - LAST_TS) / 60 ))
  if (( AGE < 30 )); then
    ok "relay.log 最近 ${AGE} 分钟内有活动"
  else
    warn "relay.log 最近活动在 ${AGE} 分钟前（若刚在用模型则异常）"
    WARNINGS+=("relay.log 静默 ${AGE} 分钟")
  fi
fi

# ---------- 5. Clash 代理 ----------
echo -e "\n[5/6] Clash 代理 (127.0.0.1:$PROXY_PORT)"
if nc -z -w 2 127.0.0.1 $PROXY_PORT 2>/dev/null; then
  ok "代理端口 $PROXY_PORT 可达"
else
  fail "代理端口 $PROXY_PORT 不通（relay 上游依赖它）"
  ISSUES+=("Clash 代理 $PROXY_PORT 不通")
fi

# ---------- 6. 最近会话实际走的通道 ----------
echo -e "\n[6/6] 最近会话实际通道（仅当有会话时）"
LATEST_JSONL=$(ls -t "$SESSIONS_DIR"/*/*.jsonl 2>/dev/null | head -1)
if [[ -n "$LATEST_JSONL" ]]; then
  LAST_PROVIDER=""
  LAST_PROVIDER=$(grep '"type":"model_change"' "$LATEST_JSONL" 2>/dev/null | tail -1 | python3 -c "import sys,json;print(json.loads(sys.stdin.read()).get('provider',''))" 2>/dev/null || true)
  if [[ "$LAST_PROVIDER" == "openai-codex" ]]; then
    ok "最近会话 ($(basename $LATEST_JSONL | cut -c1-30)) → openai-codex（订阅）"
  elif [[ -n "$LAST_PROVIDER" ]]; then
    if [[ "$LAST_PROVIDER" == "openai" ]]; then
      # 历史会话走了 openai (apiKey)——若配置已改则正常，仅提示
      warn "最近会话 ($(basename $LATEST_JSONL | cut -c1-30)) 曾走 openai(apiKey)（若该会话早于本次修复则正常）"
    else
      # 其他 provider（如 deepseek）——历史记录，仅提示
      info "最近会话 provider = ${LAST_PROVIDER}（历史记录，不影响当前配置）"
    fi
  else
    info "最近会话无 model_change 记录，跳过"
  fi
else
  info "无历史会话，跳过"
fi

# ---------- 汇总 ----------
echo -e "\n=============================================="
if [[ ${#ISSUES[@]} -eq 0 && ${#WARNINGS[@]} -eq 0 ]]; then
  echo -e " ${GREEN}🎉 全部正常：新会话将走订阅 relay（openai-codex）${NC}"
  exit 0
elif [[ ${#ISSUES[@]} -eq 0 ]]; then
  echo -e " ${YELLOW}⚠️  有 ${#WARNINGS[@]} 个警告（不影响主通道）${NC}"
  for w in "${WARNINGS[@]}"; do echo "   - $w"; done
  exit 0
else
  echo -e " ${RED}❌ 发现 ${#ISSUES[@]} 个问题：${NC}"
  for i in "${ISSUES[@]}"; do echo "   - $i"; done
fi

# ---------- 修复 ----------
if [[ "$MODE" == "--fix" || "$MODE" == "--auto" ]]; then
  echo ""
  echo -e "${CYAN}开始修复…${NC}"
  # 修复 1: settings.json defaultProvider/transport
  if [[ "$DP" != "openai-codex" || "$TP" != "sse" ]]; then
    if [[ "$MODE" == "--fix" ]]; then
      read -p "  修复 settings.json（defaultProvider=openai-codex, transport=sse）？[y/N] " yn
      [[ "$yn" != "y" && "$yn" != "Y" ]] && { echo "  跳过"; } || DO_SETTINGS=1
    else
      DO_SETTINGS=1
    fi
    if [[ "${DO_SETTINGS:-0}" == "1" ]]; then
      BK="$SETTINGS.bak-$(date +%Y%m%d-%H%M%S)"
      cp "$SETTINGS" "$BK"
      python3 - "$SETTINGS" << 'PYEOF'
import json, sys
p = sys.argv[1]
d = json.load(open(p))
d['defaultProvider'] = 'openai-codex'
d['transport'] = 'sse'
if d.get('defaultModel') != 'gpt-5.6-sol':
    d['defaultModel'] = 'gpt-5.6-sol'
json.dump(d, open(p, 'w'), indent=2, ensure_ascii=False)
PYEOF
      echo "   ✅ settings.json 已修复（备份: $(basename $BK)）"
    fi
  fi
  # 修复 2: models.json baseUrl
  if [[ "$MU" != "http://127.0.0.1:8899" ]]; then
    if [[ "$MODE" == "--fix" ]]; then
      read -p "  修复 models.json（baseUrl → 127.0.0.1:8899）？[y/N] " yn
      [[ "$yn" != "y" && "$yn" != "Y" ]] && { echo "  跳过"; } || DO_MODELS=1
    else
      DO_MODELS=1
    fi
    if [[ "${DO_MODELS:-0}" == "1" ]]; then
      BK="$MODELS.bak-$(date +%Y%m%d-%H%M%S)"
      cp "$MODELS" "$BK"
      python3 - "$MODELS" << 'PYEOF'
import json, sys
p = sys.argv[1]
d = json.load(open(p))
d.setdefault('providers', {})['openai-codex'] = {'baseUrl': 'http://127.0.0.1:8899'}
json.dump(d, open(p, 'w'), indent=2, ensure_ascii=False)
PYEOF
      echo "   ✅ models.json 已修复（备份: $(basename $BK)）"
    fi
  fi
  # 修复 3: relay 未运行 → 重启
  if [[ -z "$PID" || "$PID" == "-" ]]; then
    if [[ "$MODE" == "--fix" ]]; then
      read -p "  启动 codex-relay 服务？[y/N] " yn
      [[ "$yn" != "y" && "$yn" != "Y" ]] && { echo "  跳过"; } || DO_RELAY=1
    else
      DO_RELAY=1
    fi
    if [[ "${DO_RELAY:-0}" == "1" ]]; then
      [[ -x "$RELAY_SCRIPT" ]] && "$RELAY_SCRIPT" start || {
        launchctl load "$HOME/Library/LaunchAgents/$RELAY_LABEL.plist" 2>/dev/null || \
        echo "   ❌ 无法启动 relay（请检查 ${RELAY_SCRIPT}）"
      }
      sleep 1
      NEWPID=$(launchctl list 2>/dev/null | awk -v l="$RELAY_LABEL" '$3==l {print $1}')
      [[ -n "$NEWPID" && "$NEWPID" != "-" ]] && echo "   ✅ relay 已启动 (PID $NEWPID)" || echo "   ⚠️ relay 启动失败，请手动检查"
    fi
  fi
  echo -e "\n${CYAN}修复完成，建议重跑一次本脚本确认。${NC}"
else
  echo ""
  echo -e "${CYAN}修复方式：${NC}"
  echo "   重跑本脚本:  ./pi-channel-check.sh --fix   （交互确认）"
  echo "               ./pi-channel-check.sh --auto  （自动修复）"
  echo "   或手动参考:  ~/.pi/agent/skills/pi-openai-subscription-login/SKILL.md"
fi
