---
name: "fix-codex-app-network-failure"
description: "修复 Codex App 会话重连/连接失败/响应极慢：已实测单数键 respect_system_proxy=true 为最优修复（CLI/App/subagent 无 env 均生效），launchctl setenv 为 fallback。含一键诊断/修复/验证/回滚。当用户说 Codex App 重连、连不上、很慢、subagent 卡住时使用。"
version: 2
created: "2026-08-18"
updated: "2026-08-19"
---

## When to Use

用户在 Codex App（ChatGPT 桌面版）遇到：新会话长时间"重连/连接中"、连接失败、响应极慢、subagent 频繁卡住。

本 skill 针对**已验证根因**：codex 出站代理策略默认走 `ReqwestDefault`（读 env，无 env 直连）→ 非 OpenAI 域名（Twitter/X 等，不在 Clash 规则内）直连 → 国内网络 SYN_SENT 永久卡死 → 阻塞请求。

**最优修复（2026-08-19 实测确认）**：`~/.codex/config.toml` 的 `[features] respect_system_proxy = true`（**单数**）即可让 codex 读 macOS 系统代理，**无需任何环境变量**，CLI / App app-server / subagent 三条路径全部生效。

**重要**：本 skill 内置本机（macOS + Clash Verge 7897）已验证命令。**若用户在其他机器/平台，或诊断不符，停止套用**，改用通用诊断文档 `docs/Codex App 连接失败诊断与修复.md` 因地制宜诊断（跨 macOS/Linux/Windows、代理端口自动探测）。

## Procedure

1. **确认现象**：向用户确认 Codex App 是否重连/极慢/subagent 卡住（让用户描述，不猜）。
2. **检查修复是否已生效**（快速，2 条命令）：
   - `launchctl getenv HTTPS_PROXY` 应返回 `http://127.0.0.1:7897`（若已用单数键方案则可能为空，见下）
   - `lsof -nP -iTCP -a -p $(pgrep -f 'codex.*app-server'|head -1) | grep -c SYN_SENT` 应为 `0`
   - 已生效 → 引导用户重启 App 验证即可；未生效 → 下一步。
3. **执行修复（首选：codex 维度单数键）**：
   ```toml
   # ~/.codex/config.toml
   [features]
   respect_system_proxy = true   # 注意是单数 proxy，不是 proxies！
   ```
   - **作用**：codex 的 `OutboundProxyPolicy` 从 `ReqwestDefault` 切到 `RespectSystemProxy`，直接读 macOS 系统代理（`scutil --proxy` 需已配置，如 Clash 7897）。
   - **实测（2026-08-19，codex 0.148.0-alpha.9）**：移除全部代理 env（`launchctl unsetenv HTTPS_PROXY/HTTP_PROXY/ALL_PROXY`）后：
     - CLI：`codex exec` 无 env 执行成功（exit=0），lsof 确认连接 ESTABLISHED → 127.0.0.1:7897，0 条 SYN_SENT
     - App app-server：完全退出重启后新会话秒开
     - subagent：首次创建成功、无重试（无 env 环境下）
   - **注意**：配置后需**完全退出并重启 Codex App**（app-server 启动时读配置）。
   - **验证**：`env -u HTTPS_PROXY -u HTTP_PROXY -u ALL_PROXY -u NO_PROXY codex exec "Reply OK"` 应正常返回。
4. **执行修复（fallback：launchctl 全局 env 注入）**——当单数键方案不可用时（旧版本 codex、非 macOS、或 RespectSystemProxy 模式缺陷）：
   ```bash
   launchctl setenv HTTPS_PROXY http://127.0.0.1:7897
   launchctl setenv HTTP_PROXY http://127.0.0.1:7897
   launchctl setenv ALL_PROXY http://127.0.0.1:7897
   launchctl setenv NO_PROXY "localhost,127.0.0.1,*.xiaojukeji.com,*.didichuxing.com"
   ```
   - 作用：让 macOS GUI 应用（app-server）启动时继承代理 env，所有请求走 Clash。
   - 持久化：`~/Library/LaunchAgents/com.didi.codex-proxy-env.plist`（登录自动执行 set-proxy-env.sh）。
   - **注意**：launchctl 是**全局**的（影响所有 GUI 应用）；NO_PROXY 已排除内网。端口需替换为本机实际探测值。
5. **验证持久化**：`launchctl list | grep codex-proxy-env` 应存在（仅 fallback 方案需要）。
6. **引导用户实测**：完全退出并重开 Codex App → 新会话 → 观察重连是否消失；subagent 也应秒开（本机实测 10.9s，2026-08-19 实测无重试）。
7. **诊断不符时降级**：若用户在非 macOS/非 Clash/无直连证据，**不要硬套**，改用通用诊断文档逐步排查。
8. **回滚**（如需）：
   - 单数键方案：删除 `[features] respect_system_proxy = true` 一行即可
   - fallback 方案：`launchctl unsetenv HTTPS_PROXY/HTTP_PROXY/ALL_PROXY/NO_PROXY` + `launchctl unload ~/Library/LaunchAgents/com.didi.codex-proxy-env.plist && rm ~/Library/LaunchAgents/com.didi.codex-proxy-env.plist`

## Pitfalls

- **键名单复数**：是 `respect_system_proxy`（**单数**）。复数 `respect_system_proxies` 会被 `[features]` **静默忽略**（不报错、不生效），这是 2026-08-18 误判"实测无效"的根因。
- **不要直接套用修复**：只有确认本机 app-server 无代理 / 存在直连 SYN_SENT 才修复；否则如实告知用户其他方向（网络、代理节点、账号）。
- `~/.codex/config.toml` 的 `[features] responses_websockets = false` **实测不生效**（codex 仍走 websocket），不要用它做修复或排除依据。
- **subagent 内 curl 超时是预期**：curl 子进程只认 `-x` 参数或 `HTTPS_PROXY` env，**不读 macOS 系统代理**。单数键只影响 codex 自身的 HTTP 客户端。要让 subagent 里 curl 走代理，需显式 `-x` 或子进程带 env。
- `launchctl setenv` 是**全局**的（影响所有 GUI 应用）；NO_PROXY 已排除内网（xiaojukeji/didichuxing）控制副作用。
- **换 Clash 端口/换机器**需同步更新上述命令的端口，不能硬编码 7897（命令中的端口需用本机实际探测值替换）。
- websocket/MCP **不是根因**（走代理时 websocket 能连通；MCP 并行不阻塞），诊断时快速排除、不要深挖。

## 最终最佳实践（2026-08-19 更新：单数键已实测可用）

**首选方案**（codex 维度，App+CLI+subagent 全部生效，无副作用）：

```toml
# ~/.codex/config.toml
[features]
respect_system_proxy = true
```

配置后无需 launchctl 注入，也无需任何环境变量（codex 直接读 macOS 系统代理）。若系统代理未开启（`scutil --proxy` 无输出），先开启代理软件的系统代理。

**fallback**：`respect_system_proxy` 不可用（旧版本、非 macOS、或实测发现模式缺陷）时，用 launchctl 全局注入（见 Procedure 第 4 步）。两者可共存（env 优先级更高），切换/回滚互不冲突。

## Verification

1. **单数键方案**：`env -u HTTPS_PROXY -u HTTP_PROXY -u ALL_PROXY -u NO_PROXY codex exec "Reply OK"` 返回成功（exit=0）
2. **连接层**：`lsof -nP -iTCP -a -p <codex/app-server pid> | grep 127.0.0.1:7897` 有 ESTABLISHED；SYN_SENT 连接数为 `0`
3. **系统代理确认**：`scutil --proxy | grep HTTPSProxy` 显示本机代理地址
4. **用户实测**：新 session 和 subagent 均正常秒开、无重连（2026-08-19 实测 subagent 首次创建成功无重试）
5. **fallback 方案**：`launchctl getenv HTTPS_PROXY` 返回 `http://127.0.0.1:7897`
