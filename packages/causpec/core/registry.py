"""Family 注册表：core 与 family 之间的唯一接口。

对应 design.md 第 4 节的分层规则。方向是单向的：

    families/hte_iv  ──import──>  core.registry        ✅ 允许
    core.*           ──import──>  families.*           ❌ import-linter 禁止

core 定义「一个 family 必须长什么样」，各 family 实现它并向这里报到。
core 永远不认识任何具体的 family，因此新增一种分析只需
增加一个 family 目录和一行注册。

计划定义：
- ``FamilyProtocol``  一个 family 必须提供的方法：supports(spec)、estimate(...)、
  声明的 estimand 列表、专属质量检查
- ``register(name, family)`` / ``get(name)`` / ``list_families()``
- ``route_family(spec)``  返回候选 family 与被排除的 family 及原因
  （design.md 7.6：不把问题硬塞进 backdoor 调整）

Phase 1 任务 3。
"""
