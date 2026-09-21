"""skill 形态下调用 causpec 的入口（best-effort）。

对应 design.md 第 3 节。claude.ai 上没有 MCP server，skill 通过这个脚本
调 causpec CLI。与 MCP 形态调用同一套 causpec 函数，产出同样结构的 run 目录；
manifest 中 execution_mode 记为 skill。

诚实说明：这条路径是 best-effort——agent 可能绕过脚本直接读数据。
报告页眉会注明当前形态。

Phase 2 任务 2。
"""

raise NotImplementedError("Phase 2（W4）实现")
