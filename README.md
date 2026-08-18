# Codex Network Fix

Codex App（ChatGPT 桌面版）会话重连 / 连接失败 / 响应极慢的**诊断与修复** skill。

## 根因（一句话）

Codex 的 GUI 进程（app-server）启动时**没有继承代理环境变量**，导致对非 OpenAI 域名（Twitter/X 等，不在 Clash 规则内）**直连**，在受限网络下 TCP 连接永久卡死（SYN_SENT），阻塞请求 → 表现为"重连 5 次"、响应极慢。

详细根因链见 [docs/ROOTCAUSE.md](docs/ROOTCAUSE.md)。

## 安装（直接下载方式）

### 方式 A：Codex 用户（推荐）

将 `skills/fix-codex-app-network-failure/` 整个目录复制到 `~/.codex/skills/`：

```bash
mkdir -p ~/.codex/skills
cp -r skills/fix-codex-app-network-failure ~/.codex/skills/
```

### 方式 B：pi 用户

复制到 `~/.pi/agent/skills/`：

```bash
mkdir -p ~/.pi/agent/skills
cp -r skills/fix-codex-app-network-failure ~/.pi/agent/skills/
```

### 方式 C：手动（任何 agent）

把 `skills/fix-codex-app-network-failure/SKILL.md` 内容给 agent 读取，或放到你的 agent 的 skills 目录。

## 使用

触发场景：用户在 Codex App 中遇到新会话重连 / 连接失败 / 响应极慢 / subagent 频繁卡住。

Skill 会自动：
1. 确认现象
2. 检查代理 env 是否已生效（`launchctl getenv HTTPS_PROXY` + `lsof` 查 SYN_SENT）
3. 按平台（macOS/Linux/Windows）执行修复（命令已内嵌，无需额外脚本）
4. 验证 + 回滚

**重要**：skill 内置命令中的代理端口是示例（7897），执行时会按本机实际探测值替换。若诊断不符（无直连证据），skill 会停止套用并转向其他排查方向。

## 结构

```
├── skills/
│   ├── fix-codex-app-network-failure/SKILL.md   # Codex App 连接失败诊断修复
│   └── pi-openai-subscription-login/SKILL.md    # pi + GPT 订阅账号登录（浏览器指纹转发）
├── docs/
│   ├── Codex App 连接失败诊断与修复.md           # 通用诊断文档（跨平台、agent 可执行）
│   └── ROOTCAUSE.md                             # 完整根因链与证据
└── scripts/
    ├── codex-relay.py                           # pi 转发层（curl_cffi Chrome 指纹）
    ├── set-proxy-env.sh                         # macOS 代理 env 脚本
    ├── refresh-token.py                         # OAuth token 自动刷新
    ├── com.didi.codex-relay.plist               # relay launchd 服务
    └── com.didi.codex-token-refresh.plist       # token 每日刷新定时
```

## 终极修复（官方 respect_system_proxies）

当前方案是**临时 workaround**（launchctl 全局注入）。终极方案是 codex 官方使 `respect_system_proxies = true` 真正生效（已提 issue [openai/codex#39237](https://github.com/openai/codex/issues/39237)）。

官方修复后，用户只需：
```toml
# ~/.codex/config.toml
[features]
respect_system_proxies = true
```
即可让 Codex（App + CLI）都走系统代理，无需全局 launchctl 注入。
