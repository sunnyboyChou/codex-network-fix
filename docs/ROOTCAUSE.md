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
- **治本方向**：codex 官方修复 `respect_system_proxies` 使其真正生效（当前实测无效——CLI 无 env 仍超时，仅 chatgpt.com 走 Clash 规则、其他域名仍直连）。若官方修复，则为 codex 维度（App+CLI）的精准方案，无需全局 launchctl。

## 方法论教训

1. **排除法必须先证明干预生效**：websocket 那次"禁用后耗时不变"未验证禁用是否生效，差点走偏。正确做法是验证"codex 确实不再走 websocket"（对照日志）。
2. **reqwest 默认直连**：`reqwest::Client` 不自动读 env；`Proxy::system()` 才读系统代理。codex 的 `ReqwestDefault` 策略读 env，无则直连。
3. **GUI 常驻进程 ≠ CLI**：GUI 应用（经 launchd）不继承 shell env，需 launchctl setenv 注入。
4. **排查"慢"先看网络**：`lsof -nP -iTCP -a -p <pid> | grep SYN_SENT` 是最快定位手段。
