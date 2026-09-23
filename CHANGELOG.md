# Changelog

格式参考 [Keep a Changelog](https://keepachangelog.com/)，版本号对应 plan.md 第 2 节的里程碑。

## [Unreleased]

### Added
- 仓库骨架：uv、ruff、pyright、pytest、pre-commit、CI、import-linter
- 数据文件拦截（`.gitignore` + pre-commit 钩子）
- 全目录结构与各层职责说明；三个 family 的 `family.yaml` 声明
- 垂直切片：Spec（字段级 source/status）、门控、带地址的 Result、占位符渲染、CLI
- ADR-0001（报告中的字面量数字）、ADR-0002（数据源边界）

### Changed
- design.md 0.4：
  - 派生快照不再承诺 DuckDB，只规定两条契约（可写工作副本 + 规范化内容指纹）；
    默认实现为 parquet，数据超出单机内存时再换列式引擎
  - Postgres 交付深度收敛：v0.3 只做薄 adapter + docker-compose demo，
    证明能接入只读 view 且只读来自账号权限；masked_columns 与 schema drift 后置
  - 删掉 `contradicted` 字段状态。数据与 spec 的冲突由质量检查产生 blocking issue，
    门控第 2 条已经拦住，多一个状态是两套机制做同一件事
  - `status: confirmed` 必须附 `said`（用户确认时的原话），与 source 无关。
    堵门控的根部漏洞：update_field 由模型调用，server 无从验证确认是否真发生过
  - 10.2 措辞等级定量化：代码只能降到 suggestive，causal 需人担保 untestable 假设；
    阻断检验从一份开放清单收缩到两项（overlap、instrument relevance），
    取舍原则是「置信区间已经表达的，不再设闸」；其余诊断照印不设闸
- design.md / plan.md 升到 0.3：
  - G2 从三种口径降为两种（砍掉关系型口径与数据集 B 的第三种口径）
  - 砍掉 StatsPAI 依赖；E-value 与 effective F 自写并配数值回归测试，
    未观测混杂敏感性改用 DoubleML，AR 检验入 backlog
  - 省下的约一周并入 Phase 4，使纵向 IPCW 能完整交付（含估计）
  - ADR 从计划的 5 篇减为 2 篇：只记设计文档没覆盖的决定
