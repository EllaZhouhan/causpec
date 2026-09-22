# 第三方来源登记

本文件登记 CauSpec 中直接使用、改写，或仅借鉴思路的外部项目。改写外部代码时，在文件头注明来源、版本与许可。

## 作为依赖使用

| 项目 | 许可 | 用途 |
|---|---|---|
| EconML | MIT | `CausalForestDML`（hte_backdoor baseline）、`econml.validate.DRTester`（HTE 校准） |
| DoWhy | MIT | `CausalModel` 识别核对；refuter（placebo、random common cause、data subset） |
| pandera | MIT | 基础层 DataFrame schema 检查 |
| DoubleML | BSD-3-Clause | `sensitivity_analysis`（未观测混杂敏感性） |

## 改写代码（保留原版权声明）

| 来源 | 许可 | 改写内容 |
|---|---|---|
| Baygent `causal-inference` skill：`scripts/check_refutation.py`、`references/refutation.md` | MIT | 结论措辞等级判定；阈值按频率学派诊断重新设定 |
| Baygent `references/reporting.md` | MIT | 固定结构报告、"假设写在结果之前" |

## 仅借鉴思路（未复制代码）

| 来源 | 说明 |
|---|---|
| StatsPAI（MIT） | **不作为依赖引入**。只借鉴：`target_trial/protocol.py` 的字段划分（纵向 spec 结构）、`agent/remediation.py` 的「错误到修复建议」注册表模式、`question/preregister.py` 的 post_hoc 偏离日志做法、`immortal_time_check` 的检查口径 |
| Causal desk | 未声明许可证。借鉴 core/family 分层（ADR-0005）、字段冲突不自动裁决（ADR-0003）、地址引用机制（ADR-0002）、冻结交接件回归测试（ADR-0004）、展示被排除 family 及原因、每轮只问一个问题 |

## 自写并配数值回归测试

以下是闭式公式，自己实现比引入重依赖更可控，每个都配一份对照原始文献数值例的测试（见 ADR 与 design.md 第 9 节）：

| 内容 | 对照来源 |
|---|---|
| E-value | VanderWeele & Ding (2017), *Annals of Internal Medicine* |
| Effective F 检验 | Montiel Olea & Pflueger (2013), *JBES* |
