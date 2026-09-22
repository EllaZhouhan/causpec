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
- design.md / plan.md 升到 0.3：
  - G2 从三种口径降为两种（砍掉关系型口径与数据集 B 的第三种口径）
  - 砍掉 StatsPAI 依赖；E-value 与 effective F 自写并配数值回归测试，
    未观测混杂敏感性改用 DoubleML，AR 检验入 backlog
  - 省下的约一周并入 Phase 4，使纵向 IPCW 能完整交付（含估计）
  - ADR 从计划的 5 篇减为 2 篇：只记设计文档没覆盖的决定
