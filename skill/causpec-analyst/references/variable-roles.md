# variable-roles

> 占位。Phase 2（W4）填充。

对应 design.md 7.5。不要求用户画完整 DAG——EHR 场景协变量动辄几十个，强制画图只会流于形式。取而代之：

- `variable_roles`：每个变量或变量组标一个角色，依据变量目录中的测量窗口起草
- `key_non_edges`：显式写出少数几条决定识别成立的「无边」假设

处理前是纳入调整集的**必要条件不是充分条件**（M-bias）。`suspected_collider` 只触发 warning，报告中列出调整与不调整两种结果。
