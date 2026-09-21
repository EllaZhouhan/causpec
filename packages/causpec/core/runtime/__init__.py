"""运行时：RunContext、ArtifactWriter、audit、manifest。

对应 design.md 第 14 节的 run 目录布局。

要点：
- 写文件一律临时文件 + 原子 rename
- audit.jsonl 每次工具/CLI 调用一行：时间、工具、参数 hash、输入指纹、输出 hash、是否出错
- **日志不记录原始行，也不记录凭据**

Phase 1 任务 10。
"""
