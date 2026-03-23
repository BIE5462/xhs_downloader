# 小红书关键词搜索筛选下载器

## 项目概览

| 项目 | 内容 |
|---|---|
| 核心目标 | 输入关键词，搜索相关笔记，按点赞数与评论数筛选，自动下载命中笔记的图片并保存元数据 |
| 交付形态 | `CLI + 可复用核心库` |
| 当前实现 | 已完成工程骨架、领域模型、SQLite 状态管理、登录/搜索/筛选/下载主流程、任务恢复与基础测试 |
| 运行环境 | Python `3.9+`，真实站点抓取依赖 `Playwright` |
| 输出范围 | 当前版本默认只下载图片与元数据，不处理视频 |

## 已实现能力

| 模块 | 说明 |
|---|---|
| 登录管理 | `xhs login` 打开浏览器让用户手动登录，登录后保存 `storage_state` |
| 关键词搜索 | `xhs search preview` 仅搜索与筛选；`xhs search run` 搜索、筛选并下载图片 |
| 条件筛选 | 支持 `--min-likes`、`--min-comments` |
| 状态管理 | SQLite 持久化搜索任务、笔记摘要、笔记详情、下载任务、失败记录 |
| 结果产物 | 每篇笔记写入 `manifest.json`，每次运行写入 `run_summary.json` |
| 任务恢复 | `xhs tasks resume --run-id <ID>` 恢复未完成下载任务 |
| 任务查看 | `xhs tasks list`、`xhs status --run-id <ID>` 查看状态和摘要 |

## 系统设计

| 层级 | 负责内容 |
|---|---|
| CLI | 解析命令参数、输出结果、组织配置 |
| Application | 编排登录校验、搜索采集、详情补全、下载与恢复 |
| Domain | 定义任务状态、搜索过滤规则、笔记与图片实体 |
| Adapter | Playwright 浏览器适配器、SQLite 仓储、图片下载器 |
| Infra | 日志、配置加载、路径命名、计数解析、JSON 序列化 |

## 目录结构

| 路径 | 说明 |
|---|---|
| `src/xhs_downloader/cli.py` | CLI 入口 |
| `src/xhs_downloader/application/services.py` | 应用服务与主流程编排 |
| `src/xhs_downloader/domain/` | 领域模型、过滤规则、错误定义 |
| `src/xhs_downloader/adapters/browser.py` | Playwright 登录、搜索、详情页解析 |
| `src/xhs_downloader/adapters/storage.py` | SQLite 仓储 |
| `src/xhs_downloader/adapters/downloader.py` | 图片下载器 |
| `tests/` | 基础单元测试 |

## 快速开始

### 1. 安装依赖

```bash
pip install -e .[runtime]
playwright install chromium
```

### 2. 准备配置

复制 `config.toml.example` 为 `config.toml`，按需修改路径和运行参数。

### 3. 首次登录

```bash
python -m xhs_downloader login
```

浏览器打开后手动完成登录，回到终端按回车保存登录态。

### 4. 预览关键词结果

```bash
python -m xhs_downloader search preview --keyword 穿搭 --pages 3 --min-likes 500 --min-comments 20
```

### 5. 执行下载

```bash
python -m xhs_downloader search run --keyword 穿搭 --pages 3 --min-likes 500 --min-comments 20
```

## 运行结果

| 文件 | 说明 |
|---|---|
| `downloads/<keyword>/<run_id>/<note_id>/001.jpg` | 下载后的图片 |
| `downloads/<keyword>/<run_id>/<note_id>/manifest.json` | 单篇笔记元数据 |
| `downloads/<keyword>/<run_id>/run_summary.json` | 本次运行摘要 |
| `runtime/xhs.sqlite3` | 本地状态数据库 |

## 已知限制

| 项目 | 说明 |
|---|---|
| 页面结构依赖 | 小红书网页结构调整后，可能需要更新 `browser.py` 中的选择器和解析逻辑 |
| 反爬限制 | 当前版本只做了基础节流与失败记录，没有实现复杂风控规避策略 |
| 评论数准确性 | 搜索结果卡片未必总能直接拿到评论数，若摘要缺失，详情页补全阶段会尽量纠正 |

