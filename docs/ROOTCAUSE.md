# Codex App 新会话卡顿（1m55s + 重连 5 次）——完整根因链与修复

> 2026-08-18 定稿。本文档是排查全过程的权威记录，供日后复现/迁移/治本参考。

## 现象

- Codex App 每次新起 session：harness 显示"重连"而非思考，约 1m55s 才回复（duration_ms ≈ 114,897）
- 频繁起 subagent 协作时效率大减；点击 subagent 内部也能看到重连
- 部分 subagent 不重连（网络层偶发，非继承随机）

## 完整根因链

```
app-server（codex Rust 进程）启动时无代理环境变量
  → codex 的 ReqwestDefault 策略：读 HTTP_PROXY/HTTPS_PROXY/ALL_PROXY，无则直连
  → 非 OpenAI 域名（Twitter/X 104.244.46.246 等，不在 Clash 规则内）真正直连
  → 国内网络直连 → TCP SYN_SENT 永久卡死
  → 卡住的连接阻塞/拖慢请求处理
  → 表现：新 session "重连 5 次" + 1m55s
CLI 因继承 shell 的 HTTPS_PROXY（export）而不受影响（15s）
```

**关键洞察**：CLI 与 App 是**同一个二进制**（`/Applications/ChatGPT.app/Contents/Resources/codex`），差异只在**上层启动方式决定进程是否拿到代理 env**。

## 关键证据

| # | 证据 | 结论 |
|---|---|---|
| 1 | CLI vs App 同一二进制 | 差异在进程 env，非代码 |
| 2 | `lsof` 见 app-server 直连 `104.244.46.246:443`（Twitter/X）SYN_SENT | 直连卡死是根因 |
| 3 | 走代理时 websocket 也能连（`sec-websocket-accept` 握手成功，ws_b.log） | websocket 不是"必失败" |
| 4 | launchctl 注入 env 后：SYN_SENT=0、全走 127.0.0.1:7897 | 修复生效（干预目标达成） |
| 5 | App 实测 + subagent 10.9s 完成 | 端到端验证通过 |

## 排除项（先证伪再排除）

| 假说 | 排除方法 | 结论 |
|---|---|---|
| websocket 失败 | config.toml `responses_websockets=false` 实测**不生效**（codex 仍走 ws）→ 该证伪无效；真正排除靠证据 3（走代理 ws 能连） | 非根因（但排除过程有方法论教训） |
| MCP 初始化 | 无 MCP 配置后 App 仍 114.9s | 非根因 |
| IP/账号 | Codex 正常登录 | 非根因 |

## 修复（已落地）

```bash
# 核心：给所有 GUI 应用注入代理 env（app-server 因此继承）
launchctl setenv HTTPS_PROXY http://127.0.0.1:7897
launchctl setenv HTTP_PROXY http://127.0.0.1:7897
launchctl setenv ALL_PROXY http://127.0.0.1:7897
launchctl setenv NO_PROXY "localhost,127.0.0.1,*.xiaojukeji.com,*.didichuxing.com"
```

- 持久化：LaunchAgent `~/Library/LaunchAgents/com.didi.codex-proxy-env.plist`（登录时跑 `~/tools/codex-relay/set-proxy-env.sh`）
- 恢复：`launchctl unsetenv HTTPS_PROXY` 等（或卸载 LaunchAgent）

## 边界与迁移

- **作用域**：全局（所有 GUI 应用），非仅 Codex；NO_PROXY 已排除内网域名，副作用可控
- **换 Clash 端口**：需同步修改 `set-proxy-env.sh` 的端口（收束到新端口）
- **换机器**：按该机器实际代理端口调整命令

## respect_system_proxy 实测验证记录（2026-08-18 初判 → 2026-08-19 修正）

**2026-08-18 初判**：`respect_system_proxies = true`（**复数**）在 codex 0.148.0-alpha.9 中"不生效"，据此提了 issue [openai/codex#39237](https://github.com/openai/codex/issues/39237)。

**2026-08-19 修正（issue 评论确认 + 本机实测）**：**键名写错了**——应为**单数** `respect_system_proxy`。复数键会被 `[features]` 静默忽略（自由键映射不报错），所以策略停留在 `ReqwestDefault`（读 env，无 env 直连）。单数键把 `OutboundProxyPolicy` 切到 `RespectSystemProxy`，codex 直接读 macOS 系统代理。

### 2026-08-18 实验（复数键，结果"无效"）

| 步骤 | 结果 |
|---|---|
| macOS 系统代理已设（`scutil --proxy` 显示 HTTP/HTTPS → 127.0.0.1:7897） | ✅ |
| `~/.codex/config.toml` 加 `[features] respect_system_proxies = true`（**复数**） | ✅ 解析但不生效 |
| 移除所有代理 env（`env -u HTTPS_PROXY -u HTTP_PROXY -u ALL_PROXY -u NO_PROXY`）跑 CLI | ❌ **超时 120s** |
| 观察连接 | 仅 chatgpt.com 走 Clash 规则（侥幸命中规则），**Twitter/X 等仍直连** |
| 结论 | 复数键**不**让 codex 读 macOS 系统代理（被静默忽略） |

### 2026-08-19 实测（单数键，结果"生效"）

| 步骤 | 结果 |
|---|---|
| `[features] respect_system_proxy = true`（**单数**） | ✅ 生效 |
| CLI：移除全部代理 env 跑 `codex exec "Reply OK"` | ✅ exit=0，11s 返回 |
| 连接层：lsof 观察 | ✅ 3 条 ESTABLISHED → 127.0.0.1:7897，0 条 SYN_SENT |
| App app-server：完全退出重启（launchctl env 已移除） | ✅ 新会话秒开 |
| subagent：无 env 环境下 spawn | ✅ 首次创建成功、无重试 |
| 旁证：subagent 内裸 curl 直连 chatgpt.com | ❌ 超时（预期，curl 不读系统代理，需显式 -x） |

### 对修复策略的影响

- **当前**：首选单数键 `respect_system_proxy = true`（codex 维度，App+CLI+subagent 生效，无需全局 env）
- **fallback**：单数键不可用（旧版本、非 macOS、模式缺陷）时用 launchctl 全局注入（已验证可靠，副作用可控）
- **关键坑**：键名单复数区分——复数被静默忽略不报错，容易误判为"feature 无效"
## 方法论教训

1. **排除法必须先证明干预生效**：websocket 那次"禁用后耗时不变"未验证禁用是否生效，差点走偏。正确做法是验证"codex 确实不再走 websocket"（对照日志）。
2. **reqwest 默认直连**：`reqwest::Client` 不自动读 env；`Proxy::system()` 才读系统代理。codex 的 `ReqwestDefault` 策略读 env，无则直连。
3. **GUI 常驻进程 ≠ CLI**：GUI 应用（经 launchd）不继承 shell env，需 launchctl setenv 注入。
4. **排查"慢"先看网络**：`lsof -nP -iTCP -a -p <pid> | grep SYN_SENT` 是最快定位手段。
