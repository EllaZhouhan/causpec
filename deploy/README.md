# deploy/

本地 Postgres demo（design.md 第 5 节，Phase 3 任务 3）。

`docker-compose.yml` 起一个装好数据集 B 关系型口径的 Postgres，并建**只读账号**和 **view**。

要点：
- CauSpec 连的账号只有 `SELECT` 权限，且只对 `allowed_relations` 里的 view 开放
- 只读保证来自账号权限，**不来自 prompt**（design.md 原则 3）
- `causpec-mcp doctor` 会实际尝试写入来核实这一点

快照的保留期限、磁盘加密与容量上限属于部署环境的职责，CauSpec 不实现。
