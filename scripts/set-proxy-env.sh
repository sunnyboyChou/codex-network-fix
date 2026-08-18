#!/bin/bash
# 设置 Codex app-server 所需的代理环境变量（macOS GUI 应用经 launchd 继承）
# 由 LaunchAgent com.didi.codex-proxy-env 在登录时执行
launchctl setenv HTTPS_PROXY http://127.0.0.1:7897
launchctl setenv HTTP_PROXY http://127.0.0.1:7897
launchctl setenv ALL_PROXY http://127.0.0.1:7897
launchctl setenv NO_PROXY "localhost,127.0.0.1,*.xiaojukeji.com,*.didichuxing.com"
