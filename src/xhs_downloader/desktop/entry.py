from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Optional


def _default_config_path() -> str:
    if getattr(sys, "frozen", False):
        return str(Path(sys.executable).resolve().parent / "config.toml")
    return "config.toml"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="小红书下载工作台")
    parser.add_argument("--config", default=_default_config_path(), help="配置文件路径，默认使用当前环境下的 config.toml")
    parser.add_argument("--verbose", action="store_true", help="输出详细日志")
    return parser


def main(argv: Optional[list[str]] = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    try:
        from PySide6.QtWidgets import QApplication
    except ImportError:
        print("未安装 PySide6，请先执行 `pip install -e .[desktop]`。", file=sys.stderr)
        return 2

    from .window import launch_window

    app = QApplication.instance() or QApplication(sys.argv if argv is None else ["xhs-desktop", *argv])
    return launch_window(app, config_path=args.config, verbose=args.verbose)
