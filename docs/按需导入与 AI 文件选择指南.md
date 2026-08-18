# 按需导入与 AI 文件选择指南

> 这是本仓库的最小文件路由入口。  
> 无论是人类用户还是 AI agent，先根据目标选择文件，不要默认加载或安装整个仓库。

---

## 1. 一分钟选择表

| 目标 | 必读文件 | 执行文件 | 可选文件 | 不需要加载 |
|---|---|---|---|---|
| 只启用 Codex App 1M 上下文 | `docs/Codex App 1M 上下文配置与回滚.md` | `scripts/codex-1m-context.py` | 无 | 网络修复 skill、relay、token 刷新文件、`ROOTCAUSE.md` |
| 只修复 Codex App 重连/连接失败/响应极慢 | `skills/fix-codex-app-network-failure/SKILL.md` | skill 内置命令；macOS 可按需参考 `scripts/set-proxy-env.sh` | `docs/Codex App 连接失败诊断与修复.md`、`docs/ROOTCAUSE.md` | 1M 上下文脚本、pi relay/token 文件 |
| 只让 pi 使用 ChatGPT 订阅账号 | `skills/pi-openai-subscription-login/SKILL.md` | `scripts/codex-relay.py` | 两个 launchd plist、`refresh-token.py` | 1M 上下文文件、Codex App 连接诊断文档 |
| 只做 pi OAuth token 自动刷新 | `skills/pi-openai-subscription-login/SKILL.md` 的 token 刷新章节 | `scripts/refresh-token.py` | `scripts/com.didi.codex-token-refresh.plist` | relay、1M 上下文和 Codex App 网络修复文件 |
| 同时启用 1M 并修复 App 连接 | 1M 指南 + 网络修复 skill | `scripts/codex-1m-context.py` + skill 内置网络命令 | 通用诊断文档 | pi 相关文件 |
| 只研究连接失败根因 | `docs/ROOTCAUSE.md` | 无 | 通用诊断文档 | 所有执行脚本 |

---

## 2. AI agent 的读取协议

AI 获取本仓库后，按以下顺序处理：

1. 先读本文件，根据用户目标选择一个最小文件集合。
2. 只读取该集合里的必读文件；遇到需要执行的步骤，再读取对应执行文件。
3. 可选文件只在需要背景、跨平台命令或历史证据时加载。
4. 不要因为仓库中存在某个脚本，就把它套用到无关问题。
5. 执行前必须检查本机平台、Codex 版本、配置路径、代理端口和运行时事实。
6. 修改 `~/.codex/config.toml` 前先备份；修改 App 启动环境前保留回滚命令。
7. 验证必须读取真实运行时证据，不能只看静态配置。

推荐给 AI 的入口提示：

```text
先读取 docs/按需导入与 AI 文件选择指南.md。
根据我的目标只加载最小文件集合，不要读取或执行无关的 relay、token、网络或上下文脚本。
执行前先确认本机事实，并保留回滚方案。
```

---

## 3. 场景 A：只应用 1M 上下文

### 最小文件集合

```text
docs/Codex App 1M 上下文配置与回滚.md
scripts/codex-1m-context.py
```

### 文件职责

- 指南：解释 API 上限、Codex 模型目录上限、本地配置值、95% 有效窗口、验收与风险。
- 脚本：生成独立静态模型目录，定向修改配置，创建备份，提供状态检查和回滚。

### 最短使用方式

```bash
# 在仓库根目录执行
python3 scripts/codex-1m-context.py status
python3 scripts/codex-1m-context.py enable --restart-app
```

回滚：

```bash
python3 scripts/codex-1m-context.py rollback --restart-app
```

### 不需要的文件

- `skills/fix-codex-app-network-failure/`
- `skills/pi-openai-subscription-login/`
- `scripts/codex-relay.py`
- `scripts/refresh-token.py`
- `scripts/set-proxy-env.sh`
- 两个 launchd plist
- `docs/ROOTCAUSE.md`

除非同时存在网络或 pi 登录问题，否则不要让 AI 读取或执行这些文件。

---

## 4. 场景 B：只修复 Codex App 连接失败

### AI 最小入口

```text
skills/fix-codex-app-network-failure/SKILL.md
```

该 skill 已包含诊断、修复、验证和回滚流程。安装到 Codex：

```bash
mkdir -p ~/.codex/skills
cp -r skills/fix-codex-app-network-failure ~/.codex/skills/
```

### 人类手动排查

增加读取：

```text
docs/Codex App 连接失败诊断与修复.md
```

### 只有需要深入证据时才读取

```text
docs/ROOTCAUSE.md
```

### macOS 辅助脚本

```text
scripts/set-proxy-env.sh
```

该脚本包含示例代理端口和 `NO_PROXY`，不能不经检查直接复制执行。必须按本机代理端口、公司内网域名和使用环境调整。

### 不需要的文件

- `docs/Codex App 1M 上下文配置与回滚.md`
- `scripts/codex-1m-context.py`
- pi relay、OAuth token 刷新和对应 plist

连接失败和上下文窗口是两个独立问题：1M 配置不会修复网络，代理环境也不会自动扩大上下文。

---

## 5. 场景 C：只让 pi 使用 ChatGPT 订阅账号

### 最小文件集合

```text
skills/pi-openai-subscription-login/SKILL.md
scripts/codex-relay.py
```

### 可选生产文件

| 文件 | 什么时候需要 |
|---|---|
| `scripts/com.didi.codex-relay.plist` | macOS 希望 relay 登录后自动启动并崩溃重启 |
| `scripts/refresh-token.py` | 希望在 OAuth access token 临近过期时自动刷新 |
| `scripts/com.didi.codex-token-refresh.plist` | macOS 希望定时执行 token 刷新 |

安装 skill：

```bash
mkdir -p ~/.pi/agent/skills
cp -r skills/pi-openai-subscription-login ~/.pi/agent/skills/
```

### 注意

- relay 依赖 `curl_cffi`，并需要根据本机修改代理端口。
- plist 中的绝对路径是示例，必须改成真实安装路径。
- OAuth token 只存放在本机认证文件中，不得提交到仓库。
- 这套文件不负责扩大 Codex App 上下文窗口。

---

## 6. 场景 D：1M 与连接修复同时使用

最小集合：

```text
docs/Codex App 1M 上下文配置与回滚.md
scripts/codex-1m-context.py
skills/fix-codex-app-network-failure/SKILL.md
```

建议顺序：

1. 先修复连接并确认新 App Server 不再出现异常直连或重连。
2. 再启用 1M 静态模型目录。
3. 完全重启 App。
4. 分别验证网络证据和 `task_started.model_context_window`。

两套方案的作用域不同：

- 网络修复主要改变 App Server 的代理环境。
- 1M 方案修改 Codex 模型目录和 `config.toml` 的上下文键。

组合执行时仍应分别保留回滚手段，不要用一套回滚覆盖另一套配置。

---

## 7. 全仓库文件职责

| 路径 | 类型 | 职责 | 默认是否读取 |
|---|---|---|---|
| `README.md` | 总览 | 仓库能力和入口 | 是 |
| `docs/按需导入与 AI 文件选择指南.md` | 路由 | 根据目标选择最小文件集合 | 是 |
| `docs/Codex App 1M 上下文配置与回滚.md` | 指南 | 1M 原理、启用、验收、维护和回滚 | 仅 1M 场景 |
| `scripts/codex-1m-context.py` | 执行 | 1M 配置开关、备份和状态检查 | 仅执行 1M 时 |
| `skills/fix-codex-app-network-failure/SKILL.md` | AI skill | App 重连和连接失败诊断修复 | 仅网络场景 |
| `docs/Codex App 连接失败诊断与修复.md` | 指南 | 跨平台手动诊断和修复 | 网络场景可选 |
| `docs/ROOTCAUSE.md` | 证据 | 网络问题完整根因和历史实验 | 深入研究时 |
| `scripts/set-proxy-env.sh` | 执行示例 | macOS launchctl 代理环境 | 网络场景按需 |
| `skills/pi-openai-subscription-login/SKILL.md` | AI skill | pi 订阅账号登录和转发流程 | 仅 pi 场景 |
| `scripts/codex-relay.py` | 服务 | pi 到 ChatGPT Codex 后端的本地转发 | pi 场景必需 |
| `scripts/com.didi.codex-relay.plist` | 服务配置 | macOS relay 常驻 | pi 场景可选 |
| `scripts/refresh-token.py` | 执行 | pi OAuth token 刷新 | pi 场景可选 |
| `scripts/com.didi.codex-token-refresh.plist` | 定时配置 | macOS 定时刷新 token | pi 场景可选 |

---

## 8. 导入原则

1. **优先导入 skill 目录，而不是单独复制 `SKILL.md`**，避免以后扩展引用文件时丢失上下文。
2. **执行脚本保持在仓库中运行即可**；除非确实需要全局命令，不要随意复制到系统目录。
3. **文档可以单独交给 AI 阅读**，但涉及执行时必须同时提供对应脚本。
4. **不要导入认证和运行产物**：`auth.json`、完整 `config.toml`、sessions、日志、模型缓存和 token 都不属于仓库内容。
5. **最小化上下文**：AI 只读当前目标需要的文件，可以降低误执行、配置串扰和 token 消耗。
