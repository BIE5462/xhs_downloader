from __future__ import annotations

import argparse
from typing import Any, Dict, Optional

from .adapters.browser import PlaywrightBrowserClient
from .adapters.downloader import ImageDownloader
from .adapters.storage import SQLiteRepository
from .application.services import AuthService, SearchWorkflowService
from .config import load_config
from .domain.errors import XHSError
from .infra.logging import configure_logging
from .infra.utils import dump_json


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="小红书关键词搜索筛选下载器")
    parser.add_argument("--config", default="config.toml", help="配置文件路径，默认 config.toml")
    parser.add_argument("--verbose", action="store_true", help="输出详细日志")

    subparsers = parser.add_subparsers(dest="command")

    login_parser = subparsers.add_parser("login", help="登录并保存会话")
    login_parser.add_argument("--profile-dir", default="", help="浏览器配置目录")

    search_parser = subparsers.add_parser("search", help="搜索与下载")
    search_subparsers = search_parser.add_subparsers(dest="search_command")

    preview_parser = search_subparsers.add_parser("preview", help="只搜索和筛选，不下载")
    _add_search_arguments(preview_parser, with_output_dir=False)

    run_parser = search_subparsers.add_parser("run", help="搜索、筛选并下载图片")
    _add_search_arguments(run_parser, with_output_dir=True)

    tasks_parser = subparsers.add_parser("tasks", help="任务管理")
    tasks_subparsers = tasks_parser.add_subparsers(dest="tasks_command")

    resume_parser = tasks_subparsers.add_parser("resume", help="恢复未完成任务")
    resume_parser.add_argument("--run-id", required=True, help="运行任务 ID")

    list_parser = tasks_subparsers.add_parser("list", help="列出最近任务")
    list_parser.add_argument("--limit", type=int, default=20, help="返回任务数量，默认 20")

    status_parser = subparsers.add_parser("status", help="查看任务状态")
    status_parser.add_argument("--run-id", default="", help="指定 run_id，不传则查看最近任务")

    return parser


def _add_search_arguments(parser: argparse.ArgumentParser, with_output_dir: bool) -> None:
    parser.add_argument("--keyword", required=True, help="搜索关键词")
    parser.add_argument("--pages", type=int, default=3, help="抓取页数/滚动批次，默认 3")
    parser.add_argument("--sort", default="comprehensive", help="排序方式: comprehensive/latest/hot")
    parser.add_argument("--min-likes", type=int, default=0, help="最低点赞数")
    parser.add_argument("--min-comments", type=int, default=0, help="最低评论数")
    if with_output_dir:
        parser.add_argument("--output-dir", default="", help="输出目录，默认使用配置项 download_root")


def build_services(config_path: str) -> Dict[str, Any]:
    config = load_config(config_path)
    repository = SQLiteRepository(config.db_path)
    repository.initialize()

    browser_client = PlaywrightBrowserClient(config)
    auth_service = AuthService(repository, browser_client, config)
    workflow_service = SearchWorkflowService(
        repository=repository,
        browser_client=browser_client,
        downloader=ImageDownloader(config),
        auth_service=auth_service,
        config=config,
    )
    return {
        "config": config,
        "repository": repository,
        "auth": auth_service,
        "workflow": workflow_service,
    }


def main(argv: Optional[list[str]] = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if not args.command:
        parser.print_help()
        return 1

    configure_logging(args.verbose)
    services = build_services(args.config)
    auth_service: AuthService = services["auth"]
    workflow: SearchWorkflowService = services["workflow"]

    try:
        if args.command == "login":
            session = auth_service.login(profile_dir=args.profile_dir or None)
            print(dump_json({"session": session}))
            return 0

        if args.command == "search":
            if args.search_command == "preview":
                result = workflow.preview(
                    keyword=args.keyword,
                    pages=args.pages,
                    sort=args.sort,
                    min_likes=args.min_likes,
                    min_comments=args.min_comments,
                )
                print(dump_json(result))
                return 0

            if args.search_command == "run":
                result = workflow.run(
                    keyword=args.keyword,
                    pages=args.pages,
                    sort=args.sort,
                    min_likes=args.min_likes,
                    min_comments=args.min_comments,
                    output_dir=args.output_dir or None,
                )
                print(dump_json(result))
                return 0

        if args.command == "tasks":
            if args.tasks_command == "resume":
                result = workflow.resume(args.run_id)
                print(dump_json(result))
                return 0

            if args.tasks_command == "list":
                result = workflow.list_jobs(limit=args.limit)
                print(dump_json(result))
                return 0

        if args.command == "status":
            result = workflow.status(run_id=args.run_id or None)
            print(dump_json(result))
            return 0

        parser.print_help()
        return 1
    except XHSError as exc:
        print(str(exc))
        return 2
