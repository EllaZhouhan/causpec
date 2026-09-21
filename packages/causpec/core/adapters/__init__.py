"""数据源适配器：csv、parquet、postgres。全部只读。

对应 design.md 6.1。adapter 只负责把数据源读成 DuckDB 工作副本，
不做连接、不做派生——复杂派生由数据方的 SQL view 负责。

postgres adapter 的只读保证来自数据库账号权限，不来自代码
（design.md 原则 3）；``causpec-mcp doctor`` 负责核实账号确实无写权限。

Phase 1 任务 1、Phase 3 任务 3。
"""
