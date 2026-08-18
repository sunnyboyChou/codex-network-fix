# Codex App 连接失败诊断与修复

> 面向：Codex App（ChatGPT 桌面版）出现会话重连/连接失败/响应极慢的排查与修复。
> 读者：AI agent（可逐段执行）+ 人类用户（配合提供观察与操作）。
> 原则：**先诊断、再判断、后修复；因地制宜，不强行套用任何预设方案；一切以本机客观事实为准，不猜测。**

---

## 0. 本机准备

先确认基础信息，后续所有命令都依赖它们：

```bash
# 平台检测
uname -s            # Darwin=macOS, Linux=Linux, MINGW/MSYS=Windows
# codex 可执行文件位置（App 与 CLI 共用同一二进制）
ls -la "/Applications/ChatGPT.app/Contents/Resources/codex" 2>/dev/null || which codex 2>/dev/null
# codex 配置目录
ls -d ~/.codex 2>/dev/null
# 是否有代理软件在跑（Clash/mihomo/Surge 等），记下其监听端口
lsof -nP -iTCP -sTCP:LISTEN 2>/dev/null | grep -iE 'clash|mihomo|surge|verge' | head -5
# macOS 系统代理设置
scutil --proxy 2>/dev/null | grep -E 'HTTPEnable|HTTPPort|HTTPSEnable|HTTPSPort'
```

把结果记下来（平台、代理端口、codex 路径），后续每一步都用这些值。

---

## 1. 症状确认（人机配合）

**AI 请向用户确认**（不要猜，让用户描述）：
> "Codex App 使用中是否有以下任一现象：新会话开启时长时间'重连/连接中'？回复明显比正常慢？subagent 频繁卡住？"

- 用户确认存在连接失败/重连现象 → 继续
- 用户说没有 → 告知"这不是本文档覆盖的问题"，优雅结束

**说明**：具体耗时因网络/环境差异很大，不设硬性阈值；关键是用户能明确复现"连接失败/重连"。

---

## 2. 快速排除（不拖进度）

根据已知经验，以下两类常见怀疑通常**不是**根因，快速验证后即可跳过，不要把时间耗在这里：

### 2.1 排除 websocket（快速）

Codex 默认可能尝试 websocket 传输。但实测**走代理时 websocket 能正常连通**，所以 websocket 本身不是连接失败的原因——除非你看到明确的 websocket 报错。

```bash
# 用 CLI 跑一次（下面 3.1 会详细用），观察日志中是否有 websocket 相关
# 只要 CLI 能正常回复，websocket 就不是阻塞点
```

### 2.2 排除 MCP（快速）

配置里的 MCP server 会在每次 session 启动时拉起进程。但它们**并行初始化、不阻塞主请求**——实测禁用全部 MCP 后连接问题依旧，所以 MCP 不是根因。

```bash
# 查看 MCP 配置（不必禁用，确认存在即可）
grep -c '^\[mcp_servers' ~/.codex/config.toml 2>/dev/null
```

**结论**：这两项**默认不深挖**。除非用户能提供明确证据指向它们，否则直接进入核心诊断。

---

## 3. 核心诊断：确定根因

**核心假设**：Codex 的 GUI 进程（app-server）启动时**没有继承代理环境变量**，导致对部分域名（尤其不在代理规则内的外网域名）**直连**，在受限网络下直连 TCP 卡死（SYN_SENT 悬挂），阻塞请求 → 表现为重连/慢。

### 3.1 第一步：用 CLI 建立"环境生效"的体感

CLI 与 App 是**同一个二进制**，差异只在进程启动时是否拿到代理 env。先让 CLI 带上代理跑一次，确认"带代理 → 正常"：

```bash
# 把 {PROXY_PORT} 换成第 0 步探测到的代理端口（如 7897）
export HTTPS_PROXY=http://127.0.0.1:{PROXY_PORT}
export HTTP_PROXY=http://127.0.0.1:{PROXY_PORT}
export ALL_PROXY=http://127.0.0.1:{PROXY_PORT}

# 用 codex CLI 跑一个简单任务（注意: 若 codex 不在 PATH 用绝对路径）
time codex exec -c model=gpt-5.6-sol --skip-git-repo-check "Reply with exactly: OK" 2>&1 | tail -3
```

**判定**：
- CLI 正常快速回复（数秒）→ **代理 env 有效**，环境加载没问题 → 继续 3.2
- CLI 也慢/失败 → 代理 env 本身没生效或代理端口不对，**先排查代理连通性**（curl -x http://127.0.0.1:{PROXY_PORT} https://www.google.com/ 是否通），不要继续

### 3.2 第二步：检查 App 进程是否直连（关键证据）

找 app-server 进程，看它是否有**不走代理的直连**（非本地地址、非代理端口），尤其直连到受限外网：

```bash
# 找到 app-server 进程
ps aux | grep -E 'codex.*app-server' | grep -v grep
# 假设 PID 是 {APP_PID}，看它的直连悬挂连接（macOS）
lsof -nP -iTCP -a -p {APP_PID} 2>/dev/null | grep -iE 'SYN_SENT'
# Linux
ss -tnp | grep -iE '{APP_PID}.*SYN-SENT' 2>/dev/null
# Windows
netstat -ano | findstr SYN_SENT
```

**判定**：
- **发现 SYN_SENT 直连到非本地外网 IP** → 符合假设，进入第 4 步修复
- 没有直连 → 假设不成立，**不要强行套用修复**；回到现象，考虑其他方向（网络本身、代理节点、账号等），如实告知用户

### 3.3 可选：确认直连目标归属（增强证据）

```bash
# 把 {DIRECT_IP} 换成上一步抓到的直连 IP
curl -s --max-time 3 "https://ipinfo.io/{DIRECT_IP}/org" 2>/dev/null
# 若返回类似 "AS... Twitter/Facebook/..." 等境外机构 → 佐证是受限直连
```

---

## 4. 修复：让 GUI 应用继承代理 env

**目标**：让 Codex 的 app-server（及其他 GUI 进程）启动时拿到代理环境变量，所有请求走代理。

### macOS（推荐方案：launchctl + LaunchAgent）

```bash
# 1. 临时生效（重启 App 后 app-server 继承）
launchctl setenv HTTPS_PROXY http://127.0.0.1:{PROXY_PORT}
launchctl setenv HTTP_PROXY http://127.0.0.1:{PROXY_PORT}
launchctl setenv ALL_PROXY http://127.0.0.1:{PROXY_PORT}
launchctl setenv NO_PROXY "localhost,127.0.0.1,*.xiaojukeji.com,*.didichuxing.com"

# 2. 持久化：创建 LaunchAgent（登录时自动执行）
#    文件: ~/Library/LaunchAgents/com.didi.codex-proxy-env.plist
#    内容: <dict><key>Label</key><string>com.didi.codex-proxy-env</string>
#          <key>ProgramArguments</key><array><string>/bin/bash</string>
#          <string>/path/to/set-proxy-env.sh</string></array>
#          <key>RunAtLoad</key><true/></dict>
#    其中 set-proxy-env.sh 内容就是上面 4 条 launchctl setenv 命令

# 3. 加载
launchctl load ~/Library/LaunchAgents/com.didi.codex-proxy-env.plist
```

### Linux（GUI 应用经 systemd 用户会话 / 桌面环境继承）

```bash
# 方案 A: 写入用户环境（多数桌面环境登录时读取）
echo 'export HTTPS_PROXY=http://127.0.0.1:{PROXY_PORT}' >> ~/.profile
echo 'export HTTP_PROXY=http://127.0.0.1:{PROXY_PORT}' >> ~/.profile
echo 'export ALL_PROXY=http://127.0.0.1:{PROXY_PORT}' >> ~/.profile

# 方案 B: systemd 用户环境（若用 systemd 拉起 GUI 会话）
mkdir -p ~/.config/environment.d
echo 'HTTPS_PROXY=http://127.0.0.1:{PROXY_PORT}' > ~/.config/environment.d/proxy.conf
echo 'HTTP_PROXY=http://127.0.0.1:{PROXY_PORT}' >> ~/.config/environment.d/proxy.conf
```

### Windows（GUI 应用继承用户环境变量）

```powershell
# 设置用户级环境变量（GUI 应用经资源管理器继承）
setx HTTPS_PROXY "http://127.0.0.1:{PROXY_PORT}"
setx HTTP_PROXY "http://127.0.0.1:{PROXY_PORT}"
setx ALL_PROXY "http://127.0.0.1:{PROXY_PORT}"
# 注意: setx 对已运行的进程无效，需要重新启动 Codex App
```

---

## 5. 验证（人机配合）

**AI 引导用户**：
> "请完全退出并重新打开 Codex App，开一个新会话，观察是否还有重连/连接失败。"

同时 AI 自证：

```bash
# 确认新 app-server 进程拿到了代理 env
APP_PID=$(ps aux | grep -E 'codex.*app-server' | grep -v grep | awk '{print $2}' | head -1)
ps eww -p $APP_PID 2>/dev/null | tr ' ' '\n' | grep -iE 'HTTPS_PROXY|HTTP_PROXY'
# 确认无直连悬挂
lsof -nP -iTCP -a -p $APP_PID 2>/dev/null | grep -icE 'SYN_SENT' || echo 0
```

**判定**：
- app-server 有代理 env + SYN_SENT=0 + 用户实测新会话正常 → **修复成功**，进入第 6 步收尾
- 仍异常 → 回到诊断，不要假装成功；检查代理端口是否正确、NO_PROXY 是否误伤

---

## 6. 收尾与回滚

### 收尾
- 记录本机实际配置（平台、端口、LaunchAgent 路径）到文档末尾，方便日后排查
- 提醒用户：**换代理端口/换机器时需同步更新上述命令**

### 回滚（每步都有撤销）

```bash
# macOS
launchctl unsetenv HTTPS_PROXY
launchctl unsetenv HTTP_PROXY
launchctl unsetenv ALL_PROXY
launchctl unsetenv NO_PROXY
launchctl unload ~/Library/LaunchAgents/com.didi.codex-proxy-env.plist
rm ~/Library/LaunchAgents/com.didi.codex-proxy-env.plist

# Linux
# 删除 ~/.profile 或 ~/.config/environment.d/proxy.conf 中对应行

# Windows
setx HTTPS_PROXY "" ; setx HTTP_PROXY "" ; setx ALL_PROXY ""
```

---

## 附：注意事项（AI 必须遵守）

1. **因地制宜**：本文档描述的是"缺代理 env → 直连卡死"这一根因的修复。**只有诊断确认了直连/无 env，才应用第 4 步**；否则如实告知用户，不套用。
2. **以客观事实为准**：每一步都有可观测的判定标准（SYN_SENT、env 变量、耗时），AI 必须**实际执行并读到结果**再下结论，不猜测。
3. **用户配合**：诊断和验证需要用户操作 Codex App（重开/新会话/观察现象）。每次引导用户操作后，等待用户回来反馈，再继续下一步。
4. **{PROXY_PORT} 必须替换**：所有命令中的 `{PROXY_PORT}` 都要换成第 0 步探测到的真实端口，禁止原样执行。
