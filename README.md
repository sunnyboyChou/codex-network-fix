# Codex Network Fix

Codex App（ChatGPT 桌面版）会话重连 / 连接失败 / 响应极慢的**诊断与修复** skill。

此外收录了经过真实大输入验收的 [Codex App 1M 上下文配置与回滚指南](docs/Codex%20App%201M%20上下文配置与回滚.md)，用于处理 GPT-5.6 Sol API 支持长上下文、但 Codex App 仍被模型目录限制在约 258K 的情况。

## 按需求选择文件

不需要默认加载整个仓库。人类用户或 AI agent 请先阅读 [按需导入与 AI 文件选择指南](docs/按需导入与%20AI%20文件选择指南.md)，再按目标选择最小文件集合：

| 目标 | 最小入口 |
|---|---|
| 只启用 1M 上下文 | `docs/Codex App 1M 上下文配置与回滚.md` + `scripts/codex-1m-context.py` |
| 只修复 App 连接失败 | `skills/fix-codex-app-network-failure/SKILL.md` |
| 只配置 pi 订阅账号登录 | `skills/pi-openai-subscription-login/SKILL.md` + `scripts/codex-relay.py` |
| 深入研究网络根因 | `docs/ROOTCAUSE.md` |

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
│   ├── 按需导入与 AI 文件选择指南.md             # AI/用户按目标选择最小文件集合
│   ├── Codex App 连接失败诊断与修复.md           # 通用诊断文档（跨平台、agent 可执行）
│   ├── Codex App 1M 上下文配置与回滚.md          # 1M 原理、启用、验收和一键回滚
│   └── ROOTCAUSE.md                             # 完整根因链与证据
└── scripts/
    ├── codex-1m-context.py                       # 1M 上下文启用、状态检查和定向回滚
    ├── codex-relay.py                           # pi 转发层（curl_cffi Chrome 指纹）
    ├── set-proxy-env.sh                         # macOS 代理 env 脚本
    ├── refresh-token.py                         # OAuth token 自动刷新
    ├── com.didi.codex-relay.plist               # relay launchd 服务
    └── com.didi.codex-token-refresh.plist       # token 每日刷新定时
```

## 终极修复（2026-08-19 实测：单数键 respect_system_proxy 已可用）

**首选方案**（codex 维度，App+CLI+subagent 全部生效，无需任何环境变量）：
```toml
# ~/.codex/config.toml
[features]
respect_system_proxy = true   # 注意是单数 proxy，不是 proxies！
```

**实测结果（codex 0.148.0-alpha.9，2026-08-19）**：移除全部代理 env（`launchctl unsetenv HTTPS_PROXY/HTTP_PROXY/ALL_PROXY`）后，CLI 无 env 执行成功（exit=0，lsof 确认 ESTABLISHED → 127.0.0.1:7897，0 条 SYN_SENT）、App 新会话秒开、subagent 首次创建成功无重试。

**fallback**（单数键不可用时的旧方案）：launchctl 全局注入，见 skill `skills/fix-codex-app-network-failure/SKILL.md` 与 `scripts/set-proxy-env.sh`。

> 关键坑：键名是**单数** `respect_system_proxy`。复数 `respect_system_proxies` 会被 `[features]` 静默忽略（不报错、不生效），这是 2026-08-18 误判
