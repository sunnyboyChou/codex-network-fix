---
name: "fix-codex-app-network-failure"
description: "修复 Codex App 会话重连/连接失败/响应极慢：本机已知根因（app-server 缺代理 env 导致直连卡死 SYN_SENT）与一键诊断/修复/验证/回滚。当用户说 Codex App 重连、连不上、很慢、subagent 卡住时使用。"
version: 1
created: "2026-08-18"
updated: "2026-08-18"
---

## When to Use

用户在 Codex App（ChatGPT 桌面版）遇到：新会话长时间"重连/连接中"、连接失败、响应极慢、subagent 频繁卡住。

本 skill 针对**已验证根因**：app-server（codex Rust 进程）启动时无代理环境变量 → 非 OpenAI 域名（Twitter/X 等，不在 Clash 规则内）直连 → 国内网络 SYN_SENT 永久卡死 → 阻塞请求。

**重要**：本 skill 内置本机（macOS + Clash Verge 7897）已验证命令。**若用户在其他机器/平台，或诊断不符，停止套用**，改用通用诊断文档 `~/tools/codex-relay/docs/Codex App 连接失败诊断与修复.md` 做因地制宜诊断（跨 macOS/Linux/Windows、代理端口自动探测）。

## Procedure

1. **确认现象**：向用户确认 Codex App 是否重连/极慢/subagent 卡住（让用户描述，不猜）。
2. **检查修复是否已生效**（快速，2 条命令）：
   - `launchctl getenv HTTPS_PROXY` 应返回 `http://127.0.0.1:7897`
   - `lsof -nP -iTCP -a -p $(pgrep -f 'codex.*app-server'|head -1) | grep -c SYN_SENT` 应为 `0`
   - 已生效 → 引导用户重启 App 验证即可；未生效 → 下一步。
3. **执行修复**（核心）：设置代理环境变量让 GUI 应用继承。

   **macOS（推荐）**：执行以下命令（无需额外脚本，直接内嵌）：
   ```bash
   launchctl setenv HTTPS_PROXY http://127.0.0.1:7897
   launchctl setenv HTTP_PROXY http://127.0.0.1:7897
   launchctl setenv ALL_PROXY http://127.0.0.1:7897
   launchctl setenv NO_PROXY "localhost,127.0.0.1,*.xiaojukeji.com,*.didichuxing.com"
   ```
   - 作用：让 macOS GUI 应用（app-server）启动时继承代理 env，所有请求走 Clash。
   - 若本机存在 `~/tools/codex-relay/set-proxy-env.sh` 可直接 `bash` 执行（内容即上述命令）。

   **Linux**（GUI 应用经桌面环境继承）：
   ```bash
   echo 'export HTTPS_PROXY=http://127.0.0.1:7897' >> ~/.profile
   echo 'export HTTP_PROXY=http://127.0.0.1:7897' >> ~/.profile
   echo 'export ALL_PROXY=http://127.0.0.1:7897' >> ~/.profile
   ```

   **Windows**（GUI 应用继承用户环境变量）：
   ```powershell
   setx HTTPS_PROXY "http://127.0.0.1:7897"
   setx HTTP_PROXY "http://127.0.0.1:7897"
   setx ALL_PROXY "http://127.0.0.1:7897"
   ```
   - **注意**：上述端口 `7897` 是示例，**必须替换为第 2 步探测到的本机真实代理端口**（lsof 查 Clash/mihomo 监听端口）。
4. **验证持久化**：`launchctl list | grep codex-proxy-env` 应存在（LaunchAgent 已加载，登录自动执行，防重启丢失）。
5. **引导用户实测**：完全退出并重开 Codex App → 新会话 → 观察重连是否消失；subagent 也应秒开（本机实测 10.9s）。
6. **诊断不符时降级**：若用户在非 macOS/非 Clash/无直连证据，**不要硬套**，改用通用诊断文档逐步排查。
7. **回滚**（如需）：
   - `launchctl unsetenv HTTPS_PROXY/HTTP_PROXY/ALL_PROXY/NO_PROXY`
   - `launchctl unload ~/Library/LaunchAgents/com.didi.codex-proxy-env.plist && rm ~/Library/LaunchAgents/com.didi.codex-proxy-env.plist`

## Pitfalls

- **不要直接套用修复**：只有确认本机 app-server 无代理 env / 存在直连 SYN_SENT 才修复；否则如实告知用户其他方向（网络、代理节点、账号）。
- `~/.codex/config.toml` 的 `[features] responses_websockets = false` **实测不生效**（codex 仍走 websocket），不要用它做修复或排除依据。
- `respect_system_proxies = true` **实测无效**（CLI 无 env 仍超时），不要推荐。
- `launchctl setenv` 是**全局**的（影响所有 GUI 应用）；NO_PROXY 已排除内网（xiaojukeji/didichuxing）控制副作用。
- **换 Clash 端口/换机器**需同步更新上述命令的端口，不能硬编码 7897（命令中的端口需用本机实际探测值替换）。
- websocket/MCP **不是根因**（走代理时 websocket 能连通；MCP 并行不阻塞），诊断时快速排除、不要深挖。

## Verification

1. `launchctl getenv HTTPS_PROXY` 返回 `http://127.0.0.1:7897`
2. app-server 进程（`ps aux | grep codex.*app-server`）有 HTTPS_PROXY env（`ps eww -p <pid>` 检查）
3. `lsof` 查 app-server 的 SYN_SENT 连接数为 `0`
4. 用户实测新 session 和 subagent 均正常秒开
