# 使用说明

## 文档说明

| 项目 | 内容 |
|---|---|
| 文档目标 | 帮助你从零开始安装、配置并使用小红书关键词搜索筛选下载器 |
| 适用对象 | 本地运行工具的普通使用者、测试人员、开发联调人员 |
| 当前版本能力 | 支持登录、关键词搜索、点赞/评论数筛选、图片下载、元数据保存、任务恢复 |
| 当前限制 | 默认只下载图片，不下载视频；真实抓取依赖 Playwright 和可用登录态 |

## 一、功能简介

| 功能 | 说明 |
|---|---|
| 登录管理 | 首次使用时，通过浏览器手动登录小红书，并保存本地登录状态 |
| 搜索预览 | 输入关键词后搜索相关笔记，并按点赞数、评论数筛选，先查看命中结果 |
| 批量下载 | 对命中的笔记自动抓取详情并下载图片 |
| 元数据保存 | 每篇笔记都会保存 `manifest.json`，记录标题、作者、点赞数、评论数、图片列表等信息 |
| 任务状态查询 | 可以查看最近运行记录和某次任务的执行状态 |
| 任务恢复 | 如果下载过程中中断，可以恢复未完成任务 |

## 二、环境准备

### 1. Python 版本

建议使用 `Python 3.9` 及以上版本。

当前项目已经兼容本机的 `Python 3.9.16`。

### 2. 安装依赖

在项目根目录执行：

```bash
pip install -e .[runtime]
playwright install chromium
```

说明：

| 命令 | 作用 |
|---|---|
| `pip install -e .[runtime]` | 安装项目本身以及运行时依赖 |
| `playwright install chromium` | 安装浏览器内核，供登录与页面抓取使用 |
 
如果你需要使用 PySide6 桌面工作台，请额外安装桌面端依赖：

| 命令 | 说明 |
|---|---|
| `pip install -e .[desktop]` | 安装桌面端依赖 `PySide6` |
| `pip install -e .[runtime,desktop]` | 一次性安装 CLI 抓取能力和桌面端能力 |

如果你只是查看命令帮助、运行部分本地测试，不一定立即需要 Playwright；但只要涉及真实登录或抓取，就必须安装。

## 三、配置文件

项目根目录已经提供了一个默认配置文件：[config.toml](d:/traework/xiaohongshu-downloader/xiaohongshu-downloader/config.toml)

如需调整路径或运行参数，可以直接修改它。

### 默认配置项

| 配置项 | 默认值 | 说明 |
|---|---|---|
| `data_dir` | `runtime` | 运行期数据目录 |
| `browser_profile_dir` | `runtime/browser-profile` | 浏览器用户数据目录 |
| `storage_state_path` | `runtime/storage_state.json` | 登录态保存路径 |
| `db_path` | `runtime/xhs.sqlite3` | SQLite 状态数据库路径 |
| `download_root` | `downloads` | 图片下载根目录 |
| `headless` | `false` | 是否无头模式，登录时建议保持 `false` |
| `detail_delay_ms` | `1500` | 抓取单条笔记详情前的基础等待时间，单位毫秒 |
| `download_delay_ms` | `1200` | 下载每张图片前的基础等待时间，单位毫秒 |
| `request_jitter_ms` | `400` | 详情抓取和图片下载时叠加的随机抖动，单位毫秒 |
| `download_transport` | `browser_context` | 图片下载通道，默认复用浏览器登录态和 Cookie |
| `protection_mode` | `pause` | 命中风控后的处理模式，当前默认暂停并等待人工恢复 |
| `crawl_delay_ms` | `1200` | 页面抓取节流间隔 |
| `max_retries` | `3` | 下载失败最大重试次数 |
| `download_timeout` | `30` | 单个图片下载超时时间，单位秒 |

### 配置优先级

| 优先级 | 来源 |
|---|---|
| 高 | 环境变量 |
| 中 | `config.toml` |
| 低 | 代码内默认值 |

常用环境变量示例：

```powershell
$env:XHS_DOWNLOAD_ROOT = "D:\xhs-downloads"
$env:XHS_HEADLESS = "false"
```

## 四、如何运行命令

当前项目使用模块方式启动，推荐命令格式如下：

```powershell
$env:PYTHONPATH='src'
python -m xhs_downloader --help
```

如果你已经通过 `pip install -e .[runtime]` 完成安装，也可以直接使用：

```bash
xhs --help
```

### 桌面端工作台启动

安装桌面端依赖后，可以直接使用下面任一方式启动：

```powershell
xhs-desktop --config config.toml
```

```powershell
python -m xhs_downloader.desktop.entry --config config.toml
```

| 项目 | 说明 |
|---|---|
| 推荐命令 | `xhs-desktop --config config.toml` |
| 常用参数 | `--config` 指定配置文件；`--verbose` 开启详细日志 |
| 首次使用 | 若当前没有登录态，先点击“开始登录”，浏览器登录完成后回到工作台点击“已完成登录并保存” |
| 适用场景 | 图形化查看任务历史、命中笔记、失败任务，并在界面内执行恢复下载 |

示例：

```powershell
xhs-desktop --config config.toml --verbose
```

## 五、首次登录

### 1. 执行登录命令

```powershell
$env:PYTHONPATH='src'
python -m xhs_downloader login
```

### 2. 登录流程

| 步骤 | 操作 |
|---|---|
| 1 | 命令会自动打开 Chromium 浏览器 |
| 2 | 在浏览器里手动完成小红书登录 |
| 3 | 登录成功后，回到终端按回车 |
| 4 | 工具会保存本地登录态到 `runtime/storage_state.json` |

### 3. 登录成功后会发生什么

| 文件 | 说明 |
|---|---|
| `runtime/storage_state.json` | 保存 Cookie 和登录上下文 |
| `runtime/xhs.sqlite3` | 记录当前会话状态 |

如果登录态失效，后续执行搜索命令时会提示重新登录。

## 六、搜索结果预览

预览模式只做“搜索 + 筛选”，不会下载图片，适合先检查规则是否合理。

### 示例命令

```powershell
$env:PYTHONPATH='src'
python -m xhs_downloader search preview --keyword 穿搭 --pages 3 --min-likes 500 --min-comments 20
```

### 参数说明

| 参数 | 必填 | 说明 |
|---|---|---|
| `--keyword` | 是 | 搜索关键词 |
| `--pages` | 否 | 抓取页数/滚动批次，默认 `3` |
| `--sort` | 否 | 排序方式，支持 `comprehensive`、`latest`、`hot` |
| `--min-likes` | 否 | 最低点赞数 |
| `--min-comments` | 否 | 最低评论数 |

### 返回结果

预览命令会输出 JSON，主要包含：

| 字段 | 说明 |
|---|---|
| `run_id` | 本次任务 ID |
| `candidate_count` | 搜索到的候选笔记数量 |
| `matched_count` | 筛选后命中的笔记数量 |
| `matched` | 前 20 条命中结果预览 |

## 七、执行搜索并下载图片

### 示例命令

```powershell
$env:PYTHONPATH='src'
python -m xhs_downloader search run --keyword 穿搭 --pages 2 --min-likes 500 --min-comments 20
```

如果你希望指定下载目录：

```powershell
$env:PYTHONPATH='src'
python -m xhs_downloader search run --keyword 穿搭 --pages 3 --min-likes 500 --min-comments 20 --output-dir D:\xhs-output
```

### 下载流程

| 阶段 | 说明 |
|---|---|
| 1 | 校验本地登录态是否有效 |
| 2 | 根据关键词抓取搜索结果 |
| 3 | 根据点赞数和评论数进行筛选 |
| 4 | 打开命中的笔记详情页，提取图片链接和元数据 |
| 5 | 下载图片到本地 |
| 6 | 写入 `manifest.json` 与 `run_summary.json` |
| 7 | 记录任务状态、失败信息和统计结果 |

## 八、下载结果目录说明

默认目录结构如下：

```text
downloads/
  关键词/
    run_id/
      note_id/
        001.jpg
        002.jpg
        manifest.json
      run_summary.json
```

### 文件说明

| 文件 | 说明 |
|---|---|
| `001.jpg`、`002.jpg` | 下载的笔记图片 |
| `manifest.json` | 当前笔记的元数据 |
| `run_summary.json` | 当前任务的汇总信息 |

### `manifest.json` 主要内容

| 字段 | 说明 |
|---|---|
| `run_id` | 本次运行 ID |
| `keyword` | 搜索关键词 |
| `filters` | 使用的筛选条件 |
| `note.title` | 笔记标题 |
| `note.author_name` | 作者名称 |
| `note.like_count` | 点赞数 |
| `note.comment_count` | 评论数 |
| `note.images` | 图片列表、文件名与下载状态 |

## 九、查看任务状态

### 查看最近任务

```powershell
$env:PYTHONPATH='src'
python -m xhs_downloader tasks list
```

### 查看某次任务状态

```powershell
$env:PYTHONPATH='src'
python -m xhs_downloader status --run-id 20260323_120000_穿搭
```

如果不传 `--run-id`，则默认查看最近一次任务。

### 输出内容

| 字段 | 说明 |
|---|---|
| `job.status` | 当前任务状态 |
| `stats.summary_count` | 候选笔记数量 |
| `stats.record_count` | 成功补全详情的笔记数量 |
| `stats.download_success` | 成功下载的图片数量 |
| `stats.download_failed` | 下载失败的图片数量 |
| `stats.failure_count` | 失败记录数 |

## 十、恢复未完成任务

如果程序中途中断，或者某些图片下载失败，可以恢复任务。

### 命令示例

```powershell
$env:PYTHONPATH='src'
python -m xhs_downloader tasks resume --run-id 20260323_120000_穿搭
```

### 恢复逻辑

| 场景 | 行为 |
|---|---|
| 图片已下载成功 | 直接跳过，不重复下载 |
| 图片任务未完成 | 继续下载 |
| 图片任务失败 | 按重试策略再次尝试 |
| 没有待恢复任务 | 直接返回该任务的汇总结果 |

## 十一、常见使用场景

### 场景 1：先预览，再决定是否下载

```powershell
$env:PYTHONPATH='src'
python -m xhs_downloader search preview --keyword 美甲 --pages 2 --min-likes 300 --min-comments 10
python -m xhs_downloader search run --keyword 美甲 --pages 2 --min-likes 300 --min-comments 10
```

### 场景 2：只抓高热度内容

```powershell
$env:PYTHONPATH='src'
python -m xhs_downloader search run --keyword 旅游攻略 --pages 5 --min-likes 2000 --min-comments 100
```

### 场景 3：任务中断后继续

```powershell
$env:PYTHONPATH='src'
python -m xhs_downloader tasks list
python -m xhs_downloader tasks resume --run-id <上一步查到的run_id>
```

## 十二、常见问题

### 1. 提示“未找到登录态”

原因：你还没有执行过登录，或登录态文件被删除。

处理方式：

```powershell
$env:PYTHONPATH='src'
python -m xhs_downloader login
```

### 2. 提示“登录态已失效”

原因：保存的 Cookie 已过期，或平台要求重新登录。

处理方式：重新执行登录命令。

### 3. 提示缺少 Playwright

处理方式：

```bash
pip install -e .[runtime]
playwright install chromium
```

### 4. 搜索有结果，但命中数量为 0

常见原因：

| 原因 | 说明 |
|---|---|
| 筛选条件过高 | 例如点赞数、评论数设置太高 |
| 搜索结果字段不完整 | 个别结果卡片上评论数可能提取不到 |
| 页面结构变化 | 小红书页面改版后，现有选择器可能需要调整 |

建议先降低阈值，使用 `search preview` 观察结果。

### 5. 下载失败

如果下载阶段触发“访问验证”“请求过于频繁”或图片响应变成验证页，任务会被标记为风控暂停，不会继续硬跑后续图片。此时可以稍后使用 `xhs tasks resume --run-id <ID>` 继续恢复未完成任务。

常见原因：

| 原因 | 说明 |
|---|---|
| 网络超时 | 当前网络不稳定 |
| 图片链接失效 | 源链接已不可访问 |
| 权限问题 | 输出目录无写入权限 |

建议先执行 `tasks resume` 再尝试恢复。

## 十三、开发与自检命令

| 命令 | 作用 |
|---|---|
| `python -m unittest discover -s tests -v` | 运行基础单元测试 |
| `python -m compileall src` | 做语法编译检查 |
| `$env:PYTHONPATH='src'; python -m xhs_downloader --help` | 检查 CLI 是否能正常启动 |

## 十四、注意事项

| 项目 | 说明 |
|---|---|
| 合规使用 | 仅用于处理你有权访问和使用的内容 |
| 页面结构依赖 | 小红书页面结构变化后，抓取逻辑可能需要更新 |
| 当前版本边界 | 当前版本聚焦关键词搜索、筛选、图片下载，不包含视频下载 |
| 反爬风险 | 若访问过快或频繁，平台可能要求验证或限制访问；当前版本会自动识别风控页面并暂停任务，避免把问题扩大 |

## 十五、相关文档

| 文档 | 用途 |
|---|---|
| [PROJECT_DOCUMENTATION.md](d:/traework/xiaohongshu-downloader/xiaohongshu-downloader/PROJECT_DOCUMENTATION.md) | 查看项目设计、模块划分和实现说明 |
| [config.toml](d:/traework/xiaohongshu-downloader/xiaohongshu-downloader/config.toml) | 查看和修改默认运行配置 |
| [pyproject.toml](d:/traework/xiaohongshu-downloader/xiaohongshu-downloader/pyproject.toml) | 查看项目依赖与安装入口 |
