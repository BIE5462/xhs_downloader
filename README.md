# 小红书关键词下载器

基于关键词搜索、筛选与图片下载的 CLI 工具和桌面应用。

## 功能特性

- **登录管理** - 保存本地登录态，避免重复登录
- **搜索预览** - 按点赞/评论数筛选，先预览后下载
- **批量下载** - 自动抓取详情并下载图片
- **元数据保存** - 记录标题、作者、点赞数等信息
- **任务恢复** - 中断后可继续未完成任务
- **桌面应用** - 提供 GUI 界面（可选）

## 安装

```bash
pip install -e .[runtime]
playwright install chromium

# 桌面应用（可选）
pip install -e .[desktop]
```

## 快速开始

```bash
# 登录
xhs login

# 预览搜索结果
xhs search preview --keyword 穿搭 --pages 3 --min-likes 500

# 搜索并下载
xhs search run --keyword 穿搭 --pages 3 --min-likes 500 --min-comments 20

# 恢复中断任务
xhs tasks resume --run-id <run_id>

# 查看任务列表
xhs tasks list
```

## 桌面应用

```bash
xhs-desktop
```

## 打包 EXE

如果你需要把桌面端打包给最终用户，可以在 Windows 环境执行：

```powershell
pip install -e .[runtime,desktop,build]
python scripts/build_desktop_exe.py
```

打包完成后，分发目录位于：

```text
dist/
```

默认会包含以下文件：

| 文件 | 说明 |
|---|---|
| `xhs-desktop.exe` | 桌面端可执行程序 |
| `config.toml.example` | 配置模板，建议复制为 `config.toml` 后再修改 |
| `USAGE.md` | 使用说明 |
| `README.md` | 项目简要说明 |

分发建议：

| 项目 | 说明 |
|---|---|
| 推荐方式 | 将整个 `dist` 目录打包成 zip 再发给用户 |
| 首次使用 | 让用户先把 `config.toml.example` 复制为 `config.toml`，再运行 `xhs-desktop.exe` |
| 默认配置路径 | exe 会优先读取自身所在目录下的 `config.toml` |

## 配置

复制 `config.toml.example` 为 `config.toml`，按需修改：

| 配置项 | 说明 | 默认值 |
|--------|------|--------|
| `download_root` | 下载目录 | `downloads` |
| `headless` | 无头模式 | `false` |
| `min_likes` | 最低点赞数 | `0` |
| `min_comments` | 最低评论数 | `0` |

## 目录结构

```
downloads/
  关键词/
    run_id/
      note_id/
        001.jpg
        manifest.json
      run_summary.json
```

## 文档

- [USAGE.md](USAGE.md) - 详细使用说明
- [PROJECT_DOCUMENTATION.md](PROJECT_DOCUMENTATION.md) - 项目设计文档

## 注意事项

- 仅下载图片，不支持视频
- 请合规使用，尊重平台规则
- 页面结构变化可能导致抓取失败

## 许可证

MIT
