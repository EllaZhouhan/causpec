"""causpec-mcp：本地 MCP server（主形态）。

对应 design.md 第 12 节。server 是薄壳：解析参数、执行门控、调 causpec 库、
返回 structuredContent。所有计算逻辑在 packages/causpec/ 里，不在这里。

它相对 skill 形态多提供三样保证：
1. 数据库凭据由 server 持有，只读保证来自账号权限而非 prompt（原则 3）
2. 门控在代码里，模型绕不过（11.2 节）
3. 原始行不进模型上下文（原则 4）

实现要点：
- 使用官方 MCP Python SDK
- 不修改状态的工具标注 readOnlyHint；所有工具都不修改数据源
- 返回值声明 outputSchema 并提供 structuredContent
- stdio 模式下日志只写 stderr
- ``causpec-mcp doctor``：检查依赖、连接，以及数据库账号是否确实没有写权限

Phase 3 任务 1、2。
"""
