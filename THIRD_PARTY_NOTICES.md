# 第三方来源登记

本文件登记 CauSpec 中直接使用、改写，或仅借鉴思路的外部项目。改写外部代码时，在文件头注明来源、版本与许可。

## 作为依赖使用

| 项目 | 许可 | 用途 |
|---|---|---|
| EconML | MIT | `CausalForestDML`（hte_backdoor baseline）、`econml.validate.DRTester`（HTE 校准） |
| DoWhy | MIT | `CausalModel` 识别核对；refuter（placebo、random common cause、data subset） |
| pandera | MIT | 基础层 DataFrame schema 检查 |
| StatsPAI | MIT | 可选 extra：`effective_f_test`、`anderson_rubin_test`、`dml_sensitivity`、`evalue` |
| DoubleML | BSD-3-Clause | 可选：`sensitivity_analysis`（与 StatsPAI 的 dml_sensitivity 二选一） |

## 改写代码（保留原版权声明）

| 来源 | 许可 | 改写内容 |
|---|---|---|
| Baygent `causal-inference` skill：`scripts/check_refutation.py`、`references/refutation.md` | MIT | 结论措辞等级判定；阈值按频率学派诊断重新设定 |
| Baygent `references/reporting.md` | MIT | 固定结构报告、"假设写在结果之前" |
| StatsPAI `target_trial/protocol.py` | MIT | 纵向 spec 的字段结构对齐（仅结构，不依赖其运行时） |
| StatsPAI `agent/remediation.py` | MIT | "错误到修复建议"的注册表模式 |
| StatsPAI `question/preregister.py` | MIT | 确认后变更标记为 post_hoc 的偏离日志做法 |

## 仅借鉴思路（未复制代码）

| 来源 | 说明 |
|---|---|
| Causal desk | 未声明许可证。借鉴 core/family 分层（ADR-0005）、字段冲突不自动裁决（ADR-0003）、地址引用机制（ADR-0002）、冻结交接件回归测试（ADR-0004）、展示被排除 family 及原因、每轮只问一个问题 |
