# xiaohongshu-downloader 项目概览
- 目标：提供一个基于 CLI 的小红书关键词搜索、按点赞/评论筛选，并下载图片与元数据的工具。
- 技术栈：Python 3.9+，标准库 argparse/sqlite3/urllib，运行时可选 Playwright，用于真实站点登录与页面抓取。
- 结构：`src/xhs_downloader/cli.py` 为入口；`application/services.py` 编排业务；`adapters/` 包含 Playwright、SQLite、下载器；`domain/` 是模型和规则；`infra/` 是配置、日志和工具；`tests/` 为基础单元测试。
- 平台：Windows 优先，输出目录默认在 `downloads/`，状态数据库默认在 `runtime/xhs.sqlite3`。