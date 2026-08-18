#!/usr/bin/env python3
"""为 Codex App 配置可回滚的 GPT-5.6 Sol 长上下文目录。"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import platform
import re
import shutil
import stat
import subprocess
import sys
from datetime import datetime
from pathlib import Path
from typing import Any


DEFAULT_MODEL = "gpt-5.6-sol"
DEFAULT_CONTEXT_WINDOW = 1_050_000
DEFAULT_COMPACT_LIMIT = 900_000
EFFECTIVE_CONTEXT_PERCENT = 95
CUSTOM_CATALOG_NAME = "gpt56-sol-1m.json"


class ContextSwitch:
    """管理自定义模型目录、正式配置、备份和定向回滚。"""

    def __init__(
        self,
        codex_home: Path,
        model: str,
        context_window: int,
        compact_limit: int,
    ) -> None:
        self.codex_home = codex_home
        self.model = model
        self.context_window = context_window
        self.compact_limit = compact_limit
        self.config_path = codex_home / "config.toml"
        self.remote_catalog_path = codex_home / "models_cache.json"
        self.switch_dir = codex_home / "context-window-switch"
        self.backup_dir = self.switch_dir / "backups"
        self.state_path = self.switch_dir / "state.json"
        self.catalog_dir = codex_home / "model-catalogs"
        self.custom_catalog_path = self.catalog_dir / CUSTOM_CATALOG_NAME

    def enable(self) -> None:
        """基于最新服务端快照生成静态目录并写入正式配置。"""
        self._require_files(self.config_path, self.remote_catalog_path)
        lines = self.config_path.read_text(encoding="utf-8").splitlines(keepends=True)
        current = self._current_values(lines)
        active = self._is_active(current)

        current_catalog = current["model_catalog_json"]
        if current_catalog not in (None, str(self.custom_catalog_path)):
            raise RuntimeError(
                "检测到其他 model_catalog_json，拒绝覆盖：" + repr(current_catalog)
            )

        self.switch_dir.mkdir(parents=True, exist_ok=True)
        if active and not self.state_path.is_file():
            raise RuntimeError(
                "配置已经处于启用状态，但缺少回滚 state.json。"
                "为避免生成错误基线，请先人工恢复原配置后再启用。"
            )
        if not active:
            self._write_state(current)

        backup_path = self._backup_config("before-enable")
        self._build_catalog()
        self._set_top_value(lines, "model_context_window", str(self.context_window))
        self._set_top_value(
            lines,
            "model_auto_compact_token_limit",
            str(self.compact_limit),
        )
        self._set_top_value(
            lines,
            "model_catalog_json",
            json.dumps(str(self.custom_catalog_path)),
        )
        self._atomic_write(self.config_path, "".join(lines))

        print("已启用 GPT-5.6 Sol 长上下文配置。")
        print(f"配置备份：{backup_path}")
        print(f"静态目录：{self.custom_catalog_path}")
        print("请完全退出并重新打开 Codex App；现有任务需进入新一轮才会读取新窗口。")

    def rollback(self) -> None:
        """只撤销本脚本写入的键，保留之后产生的其他配置变化。"""
        self._require_files(self.config_path, self.state_path)
        state = json.loads(self.state_path.read_text(encoding="utf-8"))
        previous = state["previous"]
        activation = state["activation"]
        lines = self.config_path.read_text(encoding="utf-8").splitlines(keepends=True)
        current = self._current_values(lines)

        expected = {
            "model_context_window": activation["model_context_window"],
            "model_auto_compact_token_limit": activation[
                "model_auto_compact_token_limit"
            ],
            "model_catalog_json": activation["model_catalog_json"],
        }
        if current != expected:
            raise RuntimeError(
                "上下文配置在启用后又被修改。为避免覆盖新配置，自动回滚已停止。\n"
                f"当前：{current}\n预期：{expected}"
            )

        backup_path = self._backup_config("before-rollback")
        self._restore_top_value(
            lines,
            "model_context_window",
            previous["model_context_window"],
        )
        self._restore_top_value(
            lines,
            "model_auto_compact_token_limit",
            previous["model_auto_compact_token_limit"],
        )
        self._restore_top_value(
            lines,
            "model_catalog_json",
            previous["model_catalog_json"],
        )
        self._atomic_write(self.config_path, "".join(lines))

        print("已回滚 GPT-5.6 Sol 长上下文配置。")
        print(f"回滚前备份：{backup_path}")
        print("请完全退出并重新打开 Codex App。")

    def status(self) -> None:
        """输出磁盘配置和自定义目录状态。"""
        self._require_files(self.config_path)
        lines = self.config_path.read_text(encoding="utf-8").splitlines(keepends=True)
        values = self._current_values(lines)
        result: dict[str, Any] = {
            "codex_home": str(self.codex_home),
            "model": self._read_top_value(lines, "model"),
            **values,
            "config_sha256": self._checksum(self.config_path),
            "switch_enabled_on_disk": self._is_active(values),
        }

        if self.custom_catalog_path.exists():
            payload = json.loads(self.custom_catalog_path.read_text(encoding="utf-8"))
            model = next(
                (
                    item
                    for item in payload.get("models", [])
                    if item.get("slug") == self.model
                ),
                None,
            )
            if model:
                result["catalog_model"] = {
                    key: model.get(key)
                    for key in (
                        "slug",
                        "context_window",
                        "max_context_window",
                        "effective_context_window_percent",
                        "auto_compact_token_limit",
                    )
                }
                result["effective_context_window"] = (
                    model["context_window"]
                    * model["effective_context_window_percent"]
                    // 100
                )

        print(json.dumps(result, ensure_ascii=False, indent=2))

    def _build_catalog(self) -> None:
        payload = json.loads(self.remote_catalog_path.read_text(encoding="utf-8"))
        matches = [
            item for item in payload.get("models", []) if item.get("slug") == self.model
        ]
        if len(matches) != 1:
            raise RuntimeError(
                f"模型目录中应恰好存在一个 {self.model}，实际为 {len(matches)} 个"
            )

        model = matches[0]
        model["context_window"] = self.context_window
        model["max_context_window"] = self.context_window
        model["effective_context_window_percent"] = EFFECTIVE_CONTEXT_PERCENT
        model["auto_compact_token_limit"] = self.compact_limit

        self.catalog_dir.mkdir(parents=True, exist_ok=True)
        self._atomic_write(
            self.custom_catalog_path,
            json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        )

    def _write_state(self, previous: dict[str, Any]) -> None:
        state = {
            "created_at": datetime.now().isoformat(),
            "previous": previous,
            "activation": {
                "model_context_window": self.context_window,
                "model_auto_compact_token_limit": self.compact_limit,
                "model_catalog_json": str(self.custom_catalog_path),
            },
        }
        self._atomic_write(
            self.state_path,
            json.dumps(state, ensure_ascii=False, indent=2) + "\n",
        )

    def _current_values(self, lines: list[str]) -> dict[str, Any]:
        return {
            "model_context_window": self._read_top_value(
                lines, "model_context_window"
            ),
            "model_auto_compact_token_limit": self._read_top_value(
                lines, "model_auto_compact_token_limit"
            ),
            "model_catalog_json": self._read_top_value(lines, "model_catalog_json"),
        }

    def _is_active(self, values: dict[str, Any]) -> bool:
        return values == {
            "model_context_window": self.context_window,
            "model_auto_compact_token_limit": self.compact_limit,
            "model_catalog_json": str(self.custom_catalog_path),
        }

    def _backup_config(self, label: str) -> Path:
        self.backup_dir.mkdir(parents=True, exist_ok=True)
        timestamp = datetime.now().strftime("%Y%m%d-%H%M%S-%f")
        destination = self.backup_dir / f"config.toml.{timestamp}.{label}.bak"
        shutil.copy2(self.config_path, destination)
        return destination

    @staticmethod
    def _require_files(*paths: Path) -> None:
        missing = [str(path) for path in paths if not path.is_file()]
        if missing:
            raise RuntimeError("缺少必要文件：" + ", ".join(missing))

    @staticmethod
    def _checksum(path: Path) -> str:
        return hashlib.sha256(path.read_bytes()).hexdigest()

    @staticmethod
    def _top_level_end(lines: list[str]) -> int:
        for index, line in enumerate(lines):
            if line.lstrip().startswith("["):
                return index
        return len(lines)

    @classmethod
    def _read_top_value(cls, lines: list[str], key: str) -> Any:
        pattern = re.compile(rf"^\s*{re.escape(key)}\s*=\s*(.*?)\s*$")
        for line in lines[: cls._top_level_end(lines)]:
            match = pattern.match(line)
            if not match:
                continue
            raw = match.group(1)
            if raw.startswith('"') and raw.endswith('"'):
                return raw[1:-1]
            try:
                return int(raw.replace("_", ""))
            except ValueError:
                return raw
        return None

    @classmethod
    def _set_top_value(cls, lines: list[str], key: str, rendered_value: str) -> None:
        pattern = re.compile(rf"^(\s*){re.escape(key)}\s*=.*$")
        top_level_end = cls._top_level_end(lines)
        for index in range(top_level_end):
            match = pattern.match(lines[index])
            if match:
                lines[index] = f"{match.group(1)}{key} = {rendered_value}\n"
                return

        insert_at = top_level_end
        while insert_at > 0 and lines[insert_at - 1].strip() == "":
            insert_at -= 1
        lines.insert(insert_at, f"{key} = {rendered_value}\n")

    @classmethod
    def _remove_top_value(cls, lines: list[str], key: str) -> None:
        pattern = re.compile(rf"^\s*{re.escape(key)}\s*=")
        for index in range(cls._top_level_end(lines)):
            if pattern.match(lines[index]):
                del lines[index]
                return

    @classmethod
    def _restore_top_value(cls, lines: list[str], key: str, value: Any) -> None:
        if value is None:
            cls._remove_top_value(lines, key)
            return
        rendered = json.dumps(value) if isinstance(value, str) else str(value)
        cls._set_top_value(lines, key, rendered)

    @staticmethod
    def _atomic_write(path: Path, text: str) -> None:
        temporary = path.with_suffix(path.suffix + ".tmp-context-switch")
        temporary.write_text(text, encoding="utf-8")
        mode = stat.S_IMODE(path.stat().st_mode) if path.exists() else 0o600
        temporary.chmod(mode)
        temporary.replace(path)


def restart_app() -> None:
    """在 macOS 上退出 ChatGPT/Codex App，并用脱离当前进程的任务重新打开。"""
    if platform.system() != "Darwin":
        raise RuntimeError("--restart-app 当前仅支持 macOS，请手动重启 Codex App")

    subprocess.Popen(
        [
            "/bin/bash",
            "-c",
            "sleep 4; /usr/bin/open -a ChatGPT",
        ],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        start_new_session=True,
    )
    subprocess.run(
        [
            "/usr/bin/osascript",
            "-e",
            'tell application "ChatGPT" to quit',
        ],
        check=True,
    )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="配置、检查或回滚 Codex GPT-5.6 Sol 长上下文"
    )
    parser.add_argument(
        "action",
        choices=("enable", "status", "rollback"),
        help="执行动作",
    )
    parser.add_argument(
        "--codex-home",
        type=Path,
        default=Path(os.environ.get("CODEX_HOME", Path.home() / ".codex")),
        help="Codex 配置目录，默认使用 CODEX_HOME 或 ~/.codex",
    )
    parser.add_argument("--model", default=DEFAULT_MODEL)
    parser.add_argument("--context-window", type=int, default=DEFAULT_CONTEXT_WINDOW)
    parser.add_argument("--compact-limit", type=int, default=DEFAULT_COMPACT_LIMIT)
    parser.add_argument(
        "--restart-app",
        action="store_true",
        help="执行成功后重启 macOS ChatGPT/Codex App",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    switch = ContextSwitch(
        args.codex_home.expanduser().resolve(),
        args.model,
        args.context_window,
        args.compact_limit,
    )

    try:
        getattr(switch, args.action)()
        if args.restart_app and args.action != "status":
            restart_app()
    except (OSError, ValueError, RuntimeError, subprocess.SubprocessError) as error:
        print(f"错误：{error}", file=sys.stderr)
        raise SystemExit(1) from error


if __name__ == "__main__":
    main()
