# 任务完成后建议检查
- 运行 `python -m unittest discover -s tests -v`
- 运行 `python -m compileall src`
- 若改动 CLI，执行 `python -m xhs_downloader --help` 验证命令分发
- 若改动真实抓取逻辑，在本地完成一次 `login` 和 `search preview` 的手工冒烟验证