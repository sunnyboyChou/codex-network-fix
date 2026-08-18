# Codex App 1M 上下文配置与回滚

> 面向：Codex App 使用 GPT-5.6 Sol，但运行时仍显示约 `258K` 上下文的用户。  
> 目标：解释限制来源，安全启用约 1M 的有效上下文，完成真实验收，并保留定向回滚能力。  
> 实测环境：macOS、ChatGPT/Codex App `26.810.52044`、内置 CLI `0.148.0-alpha.9`、GPT-5.6 Sol。不同版本和账号的服务端目录可能不同，必须以本机运行时证据为准。

---

## 1. 先理解三个窗口

为避免把 API 能力、本地配置和 Codex 产品目录混为一谈，可以把它们记为：

- **A：模型 API 规格上限**。GPT-5.6 Sol 官方 API 规格为 `1,050,000` tokens。
- **B：Codex 模型目录的 `max_context_window`**。它由 Codex 服务端模型目录下发，可能低于 A。
- **C：用户在 `config.toml` 中请求的 `model_context_window`**。

Codex 源码应用配置时取：

```text
raw_context_window = min(B, C)
effective_context_window = raw_context_window × effective_context_window_percent
```

当前 Codex 模型目录通常使用 `effective_context_window_percent = 95`，为系统提示、工具开销和输出预留空间。

例如服务端目录给 Sol 下发：

```json
{
  "context_window": 272000,
  "max_context_window": 272000,
  "effective_context_window_percent": 95
}
```

即使本地写了：

```toml
model_context_window = 1000000
```

运行时仍然是：

```text
min(272,000, 1,000,000) × 95% = 258,400
```

因此，单独修改 `model_context_window` 不一定能突破 B。

### 相关官方资料

- [Codex Configuration Reference](https://developers.openai.com/codex/config-reference/)
- [OpenAI API 模型规格](https://developers.openai.com/api/docs/models/compare)
- [Codex 应用配置时的 `min(context_window, max_context_window)` 实现](https://github.com/openai/codex/blob/main/codex-rs/models-manager/src/model_info.rs)
- [Codex 有效窗口百分比计算](https://github.com/openai/codex/blob/main/codex-rs/core/src/session/turn_context.rs)
- [Sol 收到 272K、Terra/Luna 收到更大目录上限的公开问题](https://github.com/openai/codex/issues/39144)

公开 issue 只能证明现象存在，不能证明 272K 是针对某个账号的固定策略。准确表述应是：**当前登录会话收到的 Codex 模型目录给 Sol 下发了该上限**。它可能来自灰度、套餐、账号资格或服务端配置，除非跨账号对比或 OpenAI 明确说明，否则不要进一步猜测。

---

## 2. 获取本机真实值

### 2.1 查看服务端模型目录

优先使用 App 自带的 Codex 二进制：

```bash
CODEX_BIN="/Applications/ChatGPT.app/Contents/Resources/codex"
"$CODEX_BIN" debug models \
  | python3 -c '
import json, sys
d = json.load(sys.stdin)
for m in d.get("models", []):
    if m.get("slug") in {"gpt-5.6-sol", "gpt-5.6-terra", "gpt-5.6-luna"}:
        print({k: m.get(k) for k in (
            "slug", "context_window", "max_context_window",
            "effective_context_window_percent", "auto_compact_token_limit"
        )})
'
```

服务端目录缓存通常位于：

```text
~/.codex/models_cache.json
```

不要把直接编辑该缓存作为正式方案：它会在目录刷新时被覆盖。

### 2.2 查看当前任务运行时窗口

运行时的 `task_started.model_context_window` 比磁盘配置更可信：

```bash
find ~/.codex/sessions -type f -name '*.jsonl' -print0 \
  | xargs -0 grep -h '"type":"task_started"' \
  | tail -5
```

若看到：

```json
{"type":"task_started","model_context_window":258400}
```

说明当前 App Server 仍使用 272K 原始目录窗口。

---

## 3. 为什么使用独立静态模型目录

Codex 官方配置支持：

```toml
model_catalog_json = "/absolute/path/to/models.json"
```

它会在 App Server 启动时加载一个本地静态模型目录。安全做法不是直接修改 `models_cache.json`，而是：

1. 以最新 `models_cache.json` 为源快照；
2. 复制到独立文件；
3. 只修改目标模型的 `context_window` 和 `max_context_window`；
4. 在正式配置中引用独立文件；
5. 修改前备份 `config.toml`；
6. 回滚时只恢复本次涉及的键，不覆盖之后产生的其他配置变化。

本仓库的 `scripts/codex-1m-context.py` 自动完成这些步骤。

---

## 4. 正式启用

先完全退出 Codex App 以外的长任务，并确认 `~/.codex/models_cache.json` 存在。

### 4.1 只写配置，稍后手动重启

在仓库根目录运行：

```bash
python3 scripts/codex-1m-context.py enable
```

默认写入：

```toml
model_context_window = 1050000
model_auto_compact_token_limit = 900000
model_catalog_json = "~/.codex/model-catalogs/gpt56-sol-1m.json 的绝对路径"
```

自定义目录中的 Sol 为：

```json
{
  "context_window": 1050000,
  "max_context_window": 1050000,
  "effective_context_window_percent": 95,
  "auto_compact_token_limit": 900000
}
```

预期有效窗口：

```text
1,050,000 × 95% = 997,500
```

### 4.2 macOS 一次完成启用和重启

> 命令会退出当前 ChatGPT/Codex App。先保存其他工作，并在外部 Terminal 中执行。

```bash
python3 scripts/codex-1m-context.py enable --restart-app
```

如果不使用 `--restart-app`，需完全退出并重新打开 App。仅关闭窗口不一定会重启后台 App Server。

---

## 5. 验证正式 App 是否生效

### 5.1 验证磁盘开关

```bash
python3 scripts/codex-1m-context.py status
```

预期包含：

```json
{
  "model_context_window": 1050000,
  "model_auto_compact_token_limit": 900000,
  "switch_enabled_on_disk": true,
  "effective_context_window": 997500
}
```

### 5.2 验证运行时

重启后向 Codex 发送一条新消息，再检查任务日志中的最新 `task_started`：

```bash
find ~/.codex/sessions -type f -name '*.jsonl' -print0 \
  | xargs -0 grep -h '"type":"task_started"' \
  | tail -1
```

关键字段应为：

```json
"model_context_window":997500
```

实测表明，重启后的既有任务也可以在新一轮读取新窗口；但此前已经压缩或丢弃的历史不会恢复。若需要最干净的上下文，仍建议新建任务。

---

## 6. 后端验收：客户端放开后是否真的能超过 272K

只看到 `997500` 还不能证明后端会接受大于 272K 的真实请求。可靠验收需要满足：

1. 使用隔离 `CODEX_HOME` 或已备份的正式配置；
2. 真实 `input_tokens > 272000`；
3. 模型正常返回；
4. `turn.completed` 有真实 usage；
5. 不把重复单词堆到超过 App Server 的单条字符上限。

本次实测结果：

```text
运行时有效窗口：997,500
实际 input_tokens：339,206
总 tokens：339,211
模型回复：OK
退出状态：0
```

这证明同一登录账号的后端至少接受了 339K 的 GPT-5.6 Sol 输入，因而 272K 在该环境中主要是客户端目录限制，而不是后端在 272K 处硬拒绝。

### 字符上限陷阱

第一次验收使用约 1.8M 字符，被 App Server 在模型调用前拒绝：

```text
Input exceeds the maximum length of 1048576 characters.
```

后续使用约 562K 字符、离线计数约 320K tokens 的高 token 密度文本，验收成功。不要把“字符限制”误判成“模型 token 限制”。

大输入会明显消耗使用额度。除非确实需要验证后端边界，否则检查 `task_started.model_context_window` 即可，不要频繁重复 300K+ 验收。

---

## 7. 一键回滚

### 7.1 只回滚配置

```bash
python3 scripts/codex-1m-context.py rollback
```

脚本会：

- 恢复启用前的 `model_context_window`；
- 恢复启用前的 `model_auto_compact_token_limit`；
- 删除或恢复启用前的 `model_catalog_json`；
- 保留之后产生的其他配置变化；
- 在每次变更前创建完整配置备份。

### 7.2 macOS 一次完成回滚和重启

```bash
python3 scripts/codex-1m-context.py rollback --restart-app
```

如果脚本发现这三个键在启用后又被其他程序修改，会拒绝自动回滚，避免误覆盖新配置。此时可使用输出中的备份文件人工比对。

备份目录：

```text
~/.codex/context-window-switch/backups/
```

---

## 8. 什么情况下会重新变回 272K

只要下面两项都存在且有效，普通服务端缓存刷新不会覆盖静态目录：

```toml
model_catalog_json = "/绝对路径/gpt56-sol-1m.json"
model_context_window = 1050000
```

可能回到 272K 的情况：

1. 执行回滚，移除了 `model_catalog_json`；
2. `config.toml` 被同步工具、人工修改或 App 配置迁移覆盖；
3. 自定义模型目录被删除、损坏或格式不兼容；
4. Codex App 升级后改变模型目录 schema 或配置优先级；
5. 使用其他 `CODEX_HOME`、profile 或命令行 `-c` 覆盖；
6. 切换到另一个模型，使用了该模型自己的目录上限。

服务端刷新 `~/.codex/models_cache.json` 本身不会直接覆盖独立的 `~/.codex/model-catalogs/gpt56-sol-1m.json`。

---

## 9. 风险和维护边界

1. **静态目录会固定整个模型目录快照**：启用后，服务端新增模型、说明、推理档位或指令更新不会自动进入该静态文件。若要获取最新服务端目录，应先回滚并重启，让 `models_cache.json` 完成刷新，再重新执行 `enable`；脚本随后会基于新快照重建目录并只补丁 Sol。
2. **客户端允许不等于服务端长期承诺**：本次 339K 验收成功不代表所有账号、版本和时间点都必然支持完整 1.05M。
3. **App 更新后重新验证**：升级后先运行 `status`，再检查真实 `task_started`；不要只看配置文件。
4. **不要提交本机目录或认证信息**：`auth.json`、完整 `config.toml`、sessions 和模型请求日志不得进入仓库。
5. **配置优先级可能变化**：profile、项目配置、管理策略和命令行覆盖都可能改变最终值。
6. **使用额度**：超长上下文会增加 token 消耗、缓存和压缩成本，应按任务需要启用。

---

## 10. 最短操作清单

```bash
# 1. 查看当前服务端目录
/Applications/ChatGPT.app/Contents/Resources/codex debug models > /tmp/codex-models.json

# 2. 启用并重启（macOS）
python3 scripts/codex-1m-context.py enable --restart-app

# 3. App 重启后发送一条消息，再确认运行时为 997500
find ~/.codex/sessions -type f -name '*.jsonl' -print0 \
  | xargs -0 grep -h '"type":"task_started"' \
  | tail -1

# 4. 查看状态
python3 scripts/codex-1m-context.py status

# 5. 一键回滚并重启
python3 scripts/codex-1m-context.py rollback --restart-app
```
