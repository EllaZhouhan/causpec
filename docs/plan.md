# CauSpec 开发计划

版本：0.3
作者：Han Zhou
更新：2026-09-22
配套文档：design.md

---

## 1. 原则

- 服务求职：尽早有可展示的版本，之后逐版加深。
- 每个任务约一天，对应一个 PR，自然满足每天至少一次有意义的 commit。
- 能复用就复用（design.md 中的【复用】标记），自己写的部分集中在 spec、质量检查、门控、报告，以及你自己的两种方法。
- 计划中的周数已包含约 20% 的缓冲。

---

## 2. 里程碑

| 版本 | 周 | 日期（参考） | 内容 | 对外展示 |
|---|---|---|---|---|
| v0.0 | W1 | 9/21–9/27 | 研究代码产品化、contracts、合成数据 A | 无 |
| v0.1 | W3 | 10/5–10/11 | HTE 端到端切片：CSV、质量检查、估计、占位符报告、CLI | 本地 CLI 演示 |
| v0.2 | W4 | 10/12–10/18 | skill、skill+CLI 形态、golden tasks 初版 | claude.ai 演示 |
| v0.3 | W5 | 10/19–10/25 | 本地 MCP、门控、Postgres demo | 三个 demo；更新 CV，开始投递 |
| v0.4 | W7 | 11/2–11/8 | 纵向 IPCW | 纵向分析演示 |
| v1.0 | W8 | 11/9–11/15 | README、Related work、视频、博客 | 完整作品集 |

0.3 版调整：砍掉关系型口径与数据集 B 的第三种口径、砍掉 StatsPAI 依赖，约省一周；这一周并入 Phase 4，使纵向 IPCW 能完整交付（含估计）。

---

## 3. 前置事项

- 与合作者确认研究代码的开源许可；确认之前仓库保持 private。
- pre-commit 从第一天起阻止 csv、parquet、xlsx、duckdb 等数据文件进入提交。
- 在 GitHub 个人设置中开启"显示私有仓库贡献"。
- 在 README 草稿中列出外部来源及其许可：EconML、pandera、DoWhy、Baygent 为 MIT，DoubleML 为 BSD-3；StatsPAI（MIT）不作为依赖引入，只借鉴字段结构与做法；Causal desk 未声明许可证，只借鉴思路，不复制代码。

---

## 4. 分阶段任务

### Phase 0（W1）

1. 仓库初始化：uv、ruff、pyright、pytest、pre-commit、CI、import-linter（规则：core 不导入 family）
2. contracts：Spec（字段级 source 与 status、variable_roles、key_non_edges）、QualityIssue、Result（带地址）、Manifest
3. 把 DMLIV 迁入 families/hte_iv，剥离 I/O，并写数值回归测试
4. 合成数据 A（HTE 部分）生成器，带真值
5. ADR：只记设计文档没覆盖、或反直觉容易被后人「优化」掉的决定。
   已写：0001（报告中的字面量数字）、0002（数据源边界）。
   不写：计算在服务端、字段级确认、core/family 分层、外部代码复用策略——
   这些 design.md 与 THIRD_PARTY_NOTICES 已经写清楚，ADR 只会是重复。

### Phase 1（W2–W3）

1. csv/parquet adapter、DuckDB 快照、规范化指纹
2. 轻量 mapping 与变量目录
3. family.yaml 的 estimand 声明、route_family 与 estimand 对账；变量角色图渲染（可选 DoWhy 识别核对）
4. 基础层质量检查（【复用】pandera）与 NULL 编码检测
5. 时间一致性与可识别性检查；instrument relevance（effective F 自写 + 对照原论文数值例的回归测试；AR 检验入 backlog）
6. 数据集 C 生成器，建立注入问题到 check_id 的映射，接入 CI
7. hte_backdoor family（【复用】EconML CausalForestDML）
8. HTE 校准（hte_backdoor【复用】EconML DRTester；hte_iv 用 IV 版本得分自写）与排序稳定性
9. 敏感性与反驳（【复用】DoWhy refuter、DoubleML sensitivity_analysis；E-value 自写 + 数值回归测试）
10. runtime：RunContext、原子写入、audit、manifest
11. 报告：地址解析、占位符渲染、措辞等级判定（【复用】改写 Baygent check_refutation.py，保留 MIT 声明）
12. CLI：quality、estimate、report（打 tag v0.1）

### Phase 2（W4）

1. SKILL.md 与 references（【复用】参考 Baygent causal-inference 的结构与关键规则）
2. scripts/run.py 与 wheel；在 claude.ai 上验证
3. golden tasks 10 个与评分表；加载 skill 与不加载的对照（【复用】参考 Baygent evals 的组织方式）（打 tag v0.2）

### Phase 3（W5）

1. MCP server：工具、readOnlyHint、outputSchema；数据源边界（root / allowed_relations，见 ADR-0002）
2. 门控与结构化错误（注册表模式参考 StatsPAI agent/remediation.py，仅借鉴做法）
3. postgres adapter；docker-compose 中使用只读账号和 view；doctor 与 schema drift 检查
4. 数据集 B 的两种口径（宽表、长事件表）与鲁棒性 evals
5. 录制三个 demo：成功路径、只改 mapping 的换口径路径、数据有问题时拒绝下结论的安全失败路径（打 tag v0.3）

v0.3 之后：仓库公开（许可问题已解决的前提下），替换 CV 中"AI Agent Integration"一段，开始投递。

### Phase 4（W6–W7）

1. 先写 longitudinal-ipcw.md：事件角色与估计量定义（design.md 7.3 节 TODO）
2. longitudinal spec，字段结构对齐 target trial（对齐 StatsPAI TargetTrialProtocol 的字段划分，不引入依赖）
3. 迁入你的 IPCW 并写数值回归测试；补上数据集 A 的纵向部分（informative censoring、变长轨迹、真值）
4. 纵向质量检查（immortal time 检查的口径参考 StatsPAI immortal_time_check，仅借鉴做法）
5. 纵向输出：各 lag 的效应、at-risk 人数、权重与 ESS、clipping 敏感性
6. golden tasks 扩充到 20 个以上（打 tag v0.4）

### Phase 5（W8）

1. examples/deployments：demo-hospital、demo-retail，以及数据集 D
2. README：定位、架构图、demo GIF、Related work、外部来源与许可
3. demo 视频（3–5 分钟）；技术博客（打 tag v1.0）

---

## 5. Git 规范

- main 始终可运行；功能分支经 PR 合并，CI 通过后才能合并。
- commit message 采用 conventional commits 格式。
- 每个里程碑打 tag 并更新 CHANGELOG。
- 只做了调研的日子，提交一篇 ADR。
- 复用外部代码时，在文件头注明来源、版本与许可，并在 THIRD_PARTY_NOTICES 中登记。

---

## 6. 风险

| 风险 | 应对 |
|---|---|
| 研究代码暂不能开源 | 先用接口一致的参考实现替代，确认后再替换 |
| 真实数据误入仓库 | pre-commit 拦截；只使用合成数据 |
| 闭式诊断量（E-value、effective F）自写出错 | 每个都配一份对照原论文数值例的回归测试，测试先于实现 |
| 纵向语义复杂 | 先写文档后写代码；不阻塞 v0.3 投递 |
| 范围蔓延 | 新想法先记入 backlog，只在里程碑之间评估 |
