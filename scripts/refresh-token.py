#!/usr/bin/env python3
"""
codex-token-refresh: 自动刷新 pi 的 openai-codex OAuth token

pi 的 auth.json 中 openai-codex credential 是 OAuth 类型（{type, access, refresh, expires, accountId}），
access token 约 10 天过期。本脚本用 refresh token 换新 access token，并写回 auth.json。

用法:
    python3 refresh-token.py          # 若 24h 内将过期则刷新，否则跳过
    python3 refresh-token.py --force  # 强制刷新
    python3 refresh-token.py --check  # 只检查剩余有效期

配合 launchd（每日运行）或 crontab 使用。
"""
import argparse
import json
import os
import sys
import time

from curl_cffi import requests

AUTH_PATH = os.path.expanduser("~/.pi/agent/auth.json")
TOKEN_URL = "https://auth.openai.com/oauth/token"
CLIENT_ID = "app_EMoamEEZ73f0CkXaXp7hrann"  # pi 内置 openai-codex 的 client_id
PROXY = "http://127.0.0.1:7897"
# 提前多少毫秒刷新（默认 24 小时前）
REFRESH_BEFORE_MS = 24 * 3600 * 1000


def load_auth():
    with open(AUTH_PATH) as f:
        return json.load(f)


def save_auth(auth):
    with open(AUTH_PATH, "w") as f:
        json.dump(auth, f, indent=2)


def refresh(refresh_token):
    resp = requests.post(
        TOKEN_URL,
        data={
            "grant_type": "refresh_token",
            "refresh_token": refresh_token,
            "client_id": CLIENT_ID,
        },
        headers={"Content-Type": "application/x-www-form-urlencoded"},
        impersonate="chrome",          # token 端点实测 node 也可通，但用 chrome 指纹最稳
        proxies={"https": PROXY},
        timeout=30,
    )
    if resp.status_code != 200:
        raise RuntimeError(f"refresh failed: {resp.status_code} {resp.text[:200]}")
    data = resp.json()
    missing = [k for k in ("access_token", "refresh_token", "expires_in") if k not in data]
    if missing:
        raise RuntimeError(f"refresh response missing fields: {missing}")
    return {
        "access": data["access_token"],
        "refresh": data["refresh_token"],
        "expires": int(time.time() * 1000) + int(data["expires_in"]) * 1000,
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--force", action="store_true", help="强制刷新")
    ap.add_argument("--check", action="store_true", help="只显示剩余有效期")
    args = ap.parse_args()

    auth = load_auth()
    cred = auth.get("openai-codex")
    if not cred or cred.get("type") != "oauth":
        print("❌ auth.json 中没有 openai-codex oauth credential")
        sys.exit(1)

    now_ms = int(time.time() * 1000)
    expires = cred.get("expires", 0)
    remain_h = (expires - now_ms) / 3600000
    print(f"当前 access token 剩余: {remain_h:.1f} 小时")

    if args.check:
        return

    if not args.force and expires - now_ms > REFRESH_BEFORE_MS:
        print("✅ 尚未临近过期，跳过刷新")
        return

    print("🔄 开始刷新...")
    new_tokens = refresh(cred["refresh"])
    cred["access"] = new_tokens["access"]
    cred["refresh"] = new_tokens["refresh"]
    cred["expires"] = new_tokens["expires"]
    save_auth(auth)
    new_remain_h = (new_tokens["expires"] - now_ms) / 3600000
    print(f"✅ 刷新完成，新 token 剩余 {new_remain_h:.1f} 小时")


if __name__ == "__main__":
    main()
