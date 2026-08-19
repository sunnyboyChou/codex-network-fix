---
name: "pi-openai-subscription-login"
description: "让 pi（pi-coding-agent）通过 ChatGPT 订阅账号（不耗 API credits）使用 gpt-5.6 等模型。核心：本地转发层用 curl_cffi 模拟 Chrome TLS 指纹，绕过 Cloudflare 对 Node.js 非浏览器指纹的 403 风控。当 pi 中 openai-codex 认证失败、api 403、或想用订阅账号免费调 GPT 时使用。"
version: 2
created: "2026-08-18"
updated: "2026-08-19"
---

## When to Use

- pi 里 `openai-codex` provider 认证失败（Cloudflare 403 challenge）
- 有 ChatGPT Plus/Pro 订阅，想通过 pi 免费使用 gpt-5.6 系列（不消耗 API credits）
- pi 直接访问 `chatgpt.com/backend-api` 报 `cf-mitigated: challenge`

**根因**：Cloudflare Managed Challenge 按 **TLS 指纹（JA3/JA4）** 识别客户端——Node.js（pi 的 undici fetch）指纹=非浏览器 → 直接 403；而 Codex App 是 Chromium 内核（浏览器指纹）→ 放行。**解法**：本地转发层用 `curl_cffi impersonate="chrome"` 伪造浏览器指纹。

## 前置条件

- 已有 **ChatGPT Plus/Pro 订阅**（OAuth 登录，不消耗 API credits）
- 已安装 `curl_cffi`（Python）：`python3 -m pip install curl_cffi`
- Clash 代理运行在 127.0.0.1:7897（或改 codex-relay.py 的 PROXY 常量）

## 架构

```
pi (openai-codex / gpt-5.6-sol)
  ├─ baseUrl → http://127.0.0.1:8899（models.json 覆盖）
  └─ transport: "sse"（settings.json）
        ▼
  [codex-relay.py] (按需启动 / launchd 常驻, 端口 8899)
        │  curl_cffi impersonate="chrome"（Chrome TLS 指纹）
        │  走 Clash 代理
        ▼
  chatgpt.com/backend-api  ← 200 ✅（绕过 Cloudflare 指纹风控）
```

**relay 启动方式（二选一）**：
- **按需懒启动（推荐，2026-08-19 本机采用）**：不随开机自启，跟随 `pi` / `pi-web` 命令自动拉起（见下文「relay 按需启动」）
- **launchd 常驻**：开机自启 + 崩溃重启，适合多终端/定时场景（见下文「launchd 常驻」）

## 实施步骤

### 1. 部署转发层

```bash
# 下载/复制 codex-relay.py 到本地（脚本见仓库 scripts/codex-relay.py）
# 依赖
python3 -m pip install curl_cffi

# 启动（前台测试）
python3 codex-relay.py --port 8899

# 生产：两种方式任选其一
# 方式 A（推荐）：按需懒启动——跟随 pi/pi-web 命令自动拉起（见下节）
# 方式 B：launchd 常驻（开机自启 + 崩溃重启）
# 参考仓库 scripts/com.didi.codex-relay.plist
launchctl load ~/Library/LaunchAgents/com.didi.codex-relay.plist
```

### 1.1 relay 按需启动（推荐：懒加载，不常驻）

**背景（2026-08-19 采用）**：relay 只服务 pi 的 openai-codex 通道，不需要开机自启。改为跟随 `pi` / `pi-web` 命令自动拉起——首次执行时检查 8899，未监听则后台启动并等端口就绪。

在 `~/.zshrc` 追加（pi 用户级 shell 均可）：
```bash
# ---- codex-relay 懒启动（跟随 pi / pi-web 命令，不常驻）----
_codex_relay_ensure() {
  if lsof -nP -iTCP:8899 -sTCP:LISTEN >/dev/null 2>&1; then
    return 0   # 已在运行
  fi
  nohup /usr/bin/python3 /Users/didi/tools/codex-relay/codex-relay.py --port 8899 \
    >> /Users/didi/tools/codex-relay/relay.log 2>&1 &
  local i=0
  while [ $i -lt 16 ]; do
    if lsof -nP -iTCP:8899 -sTCP:LISTEN >/dev/null 2>&1; then
      break
    fi
    sleep 0.5; i=$((i+1))
  done
}
pi()      { _codex_relay_ensure; command pi "$@"; }
pi-web()  { _codex_relay_ensure; command pi-web "$@"; }
```
要点：`nohup ... &` 后台脱离会话；`lsof` 探测做幂等（重复执行不重复拉起）；`command pi` 绕过函数递归。已在本机实测：pi / pi-web 均可触发、进程数恒为 1。

### 1.2 launchd 常驻（可选：多终端/定时场景）

⚠️ launchd 只扫描 `~/Library/LaunchAgents/` 等固定目录，**仅把 plist 放 `~/tools/codex-relay/` 不会自动加载**（2026-08-19 实测踩坑：重启后 relay 未自启）。必须复制到扫描目录并加载：
```bash
cp ~/tools/codex-relay/com.didi.codex-relay.plist ~/Library/LaunchAgents/
launchctl load ~/Library/LaunchAgents/com.didi.codex-relay.plist
# 验证：launchctl list | grep codex-relay
```

### 2. 配置 pi（关键：默认通道必须是 openai-codex）

```bash
# models.json: openai-codex baseUrl → 本地转发层
cat > ~/.pi/agent/models.json << 'EOF'
{
  "providers": {
    "openai-codex": { "baseUrl": "http://127.0.0.1:8899" }
  }
}
EOF

# settings.json: 强制 SSE（避开 websocket 传输）+ 默认走订阅
# ⚠️ 三个字段缺一不可，缺失/错误会让新会话回退到 apiKey 通道：
cat > ~/.pi/agent/settings.json << 'EOF'
{
  "defaultProvider": "openai-codex",   # ★ 必须是 openai-codex，不能是 openai
  "defaultModel": "gpt-5.6-sol",
  "transport": "sse"                    # ★ 必须是 sse，不能是 auto
}
EOF

# 验证（应输出 openai-codex）：
python3 -c "import json; d=json.load(open('$HOME/.pi/agent/settings.json')); print(d['defaultProvider'])"
```

**为什么 defaultProvider 必须是 openai-codex**：若为 `openai`，不带前缀选 gpt-5.6-sol 会解析到 `api.openai.com` + sk-proj API key（订阅余额不转入 API，报 429 insufficient_quota）→ 空回复。只有 `openai-codex` 走本地 relay（OAuth 订阅，免费）。用 deepseek 时显式 `--provider deepseek`，不要依赖默认值。


### 3. 获取订阅 token（OAuth）

pi 的 openai-codex 用 OAuth（ChatGPT 账号）。token 可从已登录的 codex 环境获取：
```bash
# 方式 A: 从 ~/.codex/auth.json 复制（若 codex 已登录）
# 方式 B: pi 交互模式 /login 选 openai-codex 走 OAuth 浏览器流程
```

写入 `~/.pi/agent/auth.json`：
```json
{
  "openai-codex": {
    "type": "oauth",
    "access": "<access_token>",
    "refresh": "<refresh_token>",
    "expires": <毫秒时间戳>,
    "accountId": "<account_id>"
  }
}
```

### 4. 使用

```bash
export HTTPS_PROXY=http://127.0.0.1:7897 HTTP_PROXY=http://127.0.0.1:7897
npx pi --model openai-codex/gpt-5.6-sol "你的问题"
```

### 5. token 自动刷新（access 约 10 天过期）

每日 03:30 用 refresh token 换新（client_id=`app_EMoamEEZ73f0CkXaXp7hrann`）：
```bash
# 参考仓库 scripts/refresh-token.py
python3 refresh-token.py --force   # 手动强制刷新
# launchd 定时（参考 scripts/com.didi.codex-token-refresh.plist）
```

## 关键文件（仓库 codex-network-fix）

| 文件 | 作用 |
|---|---|
| `scripts/codex-relay.py` | 本地转发层（curl_cffi Chrome 指纹 + SSE 流式转发） |
| `scripts/com.didi.codex-relay.plist` | launchd 常驻服务定义 |
| `scripts/refresh-token.py` | OAuth token 自动刷新 |
| `scripts/com.didi.codex-token-refresh.plist` | 每日刷新定时任务 |

## Pitfalls

- **`transport: "sse"` 必须设**：pi 的 openai-codex 默认 `transport: "auto"` 优先 websocket（Node 原生实现，非浏览器指纹）→ 被 Cloudflare 拦。设 SSE 后走 HTTP 转发层。
- **转发层必须处理 zstd**：pi 的 SSE body 是 zstd 压缩的（`content-encoding: zstd`），relay 需透传该头（codex-relay.py 已处理）。
- **路径前缀**：pi 请求 `/codex/responses`（缺 `/backend-api` 前缀），relay 需自动补前缀（已处理）。
- **订阅 ≠ API credits**：Pro 订阅不转入 API 余额，`api.openai.com` 走 API key 会报 429 insufficient_quota。必须走 openai-codex provider（订阅 OAuth）。
- **defaultProvider 被改回 openai 是最常见故障**（2026-08-19 实测踩坑）：症状 = 新会话 4 次空回复/连不通；确认方法 = 看会话 jsonl 里 `model_change` 行的 provider 字段。修复 = settings.json 改回 `openai-codex`。
- **换端口**：改 codex-relay.py 的 PROXY 常量或 models.json 的 baseUrl 端口，需保持一致。

## Verification

1. `curl -s http://127.0.0.1:8899/backend-api/me -H "Authorization: Bearer <token>"` 返回 200（非 403）
2. `npx pi --model openai-codex/gpt-5.6-sol --print "hi"` 正常回复
3. `pi auth check --provider openai-codex` 返回 `status: ready`
4. token 过期后 `refresh-token.py --force` 能刷新（剩余时间回到 ~240h）
