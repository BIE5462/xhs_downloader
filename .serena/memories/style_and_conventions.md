# 风格与约定
- 使用 Python，模块按 CLI / application / adapters / domain / infra 分层。
- 领域模型主要使用 dataclass 和 Enum，函数有明确类型标注。
- CLI 使用 argparse，不依赖第三方 CLI 框架。
- 状态持久化统一通过 `SQLiteRepository`，不要在 CLI 或浏览器适配器里直接写 SQLite。
- 下载输出遵循 `downloads/<keyword>/<run_id>/<note_id>/`，笔记目录内保存图片和 `manifest.json`。