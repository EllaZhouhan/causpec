"""longitudinal_ipcw：纵向处理效应，IPCW。

估计器是作者自己的研究代码。spec 的字段结构对齐 target trial 的七个组成部分，
另加 event_roles，把 death、discharge、transfer 等事件显式指定为
outcome / competing / censoring / terminal（design.md 7.3）。

注意：StatsPAI 的 ipcw 在其仓库中仅标为 analytical-only，
只可用于合成数据上的交叉核对，**不作为参考实现**。

前置：先写 references/longitudinal-ipcw.md 明确各事件的处理方式
及估计量的解释（design.md 7.3 TODO）。

Phase 4。
"""
