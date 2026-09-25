"""hte_iv 的估计适配器。

【复用】EconML（MIT）的两个 IV 估计器。本文件只做适配：从 spec 取字段、
按数据判定 instrument 是离散还是连续、跑估计、把结果转成带地址的 Result。

两个后端，由 ``spec.estimation.params.estimator`` 选：

| | ``ivforest``（默认） | ``dmliv`` |
|---|---|---|
| 估计器 | ``econml.grf.CausalIVForest`` | ``econml.iv.dml.NonParamDMLIV`` |
| CATE 区间 | GRF honest 方差估计，一次拟合内完成 | **只能 bootstrap**——整个模型重拟合 N 次 |
| ATE 区间 | **没有**，见下 | 有 |
| 代价 | 低（实测 n=5000 约 6 秒） | 高（同样数据 × 20 次重抽样约 9 分钟） |

**默认为什么是 ivforest。** 研究代码的最终版用的是 ``dmliv``，但作为工具的默认值，
开箱即用的那个应当是站得住的那个：``dmliv`` 的区间只能靠 bootstrap，而可信的
percentile 区间需要几百次重抽样——实测每次重抽样约 26 秒，200 次就是一个半小时。
把重抽样次数调低能变快，但区间会失真：同一份数据下 20 次重抽样与 GRF 解析区间
给出的「个体显著获益人数」差了两个数量级（416 对 3）。与其给一个又慢又不可信的
默认值，不如默认走解析区间，把 ``dmliv`` 留给需要与论文口径一致的确认性分析。

``NonParamDMLIV`` 的 final model 是任意回归器，EconML 推不出它的方差，
``_get_inference_options()`` 里只有 ``bootstrap`` 一项——这不是选择，是唯一选项。
``CausalIVForest`` 走 Athey–Tibshirani–Wager 的 honest 森林方差，不需要重抽样。
两者的区间在有限样本下都可能失准（GRF 有低覆盖报告，bootstrap 在弱工具、
低事件率下不稳），因此区间的构造方式记在 ``res:primary.interval_method``，
由报告摆给读者看，不由工具替用户决定。

``ivforest`` 不产出 ``res:primary.ate_ci_*``：逐点区间不能简单平均成 ATE 区间
（忽略了协方差）。宁可不给这个地址，也不给一个没法辩护的数——引用它的报告
会渲染失败，这正是地址机制该有的行为（design.md 10.1）。

与研究代码的三处差别（plan.md Phase 0 任务 3「剥离 I/O」）：

1. **不写文件。** 原代码在函数内 ``joblib.dump(model, f"{model_name}.pkl")``；
   产物由 core/runtime 的 ArtifactWriter 原子写入 run 目录。
2. **不 print。** 原代码 ``verbose`` 打印的那一串统计量，在这里变成 Result 的地址。
3. **X 与 W 分开。** 原代码定义了 ``controls``（75 列）又定义了 ``features``（60 列），
   实际只把 features 传给 X、``W=None``，两者之差被静默丢弃。spec 里
   ``effect_modifiers``（→ X）与 ``adjustment_set``（→ W）是两个必须分别确认的字段。
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

import numpy as np

# 在模块层 import，不放进 estimate()：这样依赖缺失会在 registry.get() 时就暴露，
# 用户不会走完整个 spec 确认流程才发现跑不了。registry 会把 ImportError 转成
# 带安装命令的结构化错误。
from econml.grf import CausalIVForest
from econml.inference import BootstrapInference
from econml.iv.dml import NonParamDMLIV
from joblib import Parallel, delayed
from sklearn.ensemble import RandomForestRegressor

from causpec.core.contracts.result import Result
from causpec.core.contracts.spec import Spec
from causpec.core.registry import register

if TYPE_CHECKING:
    import pandas as pd

ESTIMATORS = ("dmliv", "ivforest")

# percentile bootstrap 区间要可信，重抽样次数不能太少：实测同一份数据下
# 20 次重抽样与 GRF 解析区间给出的「个体显著获益人数」差了两个数量级。
# 两个后端共用这个默认值，都可从 spec.estimation.params 覆盖。
DEFAULT_BOOTSTRAP_SAMPLES = 200

# 唯一值落在 {0,1} 内时，视 instrument 为二值。
_BINARY_VALUES = frozenset({0, 1})


def _column_names(spec: Spec, field: str) -> list[str]:
    """从 spec 取一个列名列表字段。缺失返回空列表。"""
    entry = spec.fields.get(field)
    if entry is None or entry.value is None:
        return []
    value = entry.value
    return [str(value)] if isinstance(value, str) else [str(v) for v in value]


def _is_binary(series: Any) -> bool:
    return set(series.dropna().unique().tolist()) <= _BINARY_VALUES


def _scalar(value: Any) -> float:
    """EconML 的 ate / ate_interval 返回 treatment 维的数组，二值处理下取第一个。"""
    return float(np.ravel(value)[0])


def _distribution(prefix: str, values: np.ndarray) -> dict[str, float]:
    q = np.percentile(values, [5, 25, 50, 75, 95])
    return {
        f"{prefix}.mean": float(np.mean(values)),
        f"{prefix}.std": float(np.std(values)),
        f"{prefix}.min": float(np.min(values)),
        f"{prefix}.q05": float(q[0]),
        f"{prefix}.q25": float(q[1]),
        f"{prefix}.median": float(q[2]),
        f"{prefix}.q75": float(q[3]),
        f"{prefix}.q95": float(q[4]),
        f"{prefix}.max": float(np.max(values)),
    }


class HteIv:
    """IV 设定下的异质处理效应。

    instrument 二值与连续都支持——``discrete_instrument`` 按数据自动判定，
    并记进 Result，因为它决定了 estimand 怎么解释（见 family.yaml）。
    """

    id = "hte_iv"

    def estimate(self, data: pd.DataFrame, spec: Spec, seed: int) -> Result:
        backend = str(spec.param("estimator", "ivforest"))
        if backend not in ESTIMATORS:
            raise ValueError(f"estimator 只能是 {'、'.join(ESTIMATORS)}，收到 {backend}")

        treatment = _column_names(spec, "treatment")[0]
        outcome = _column_names(spec, "outcome")[0]
        instruments = _column_names(spec, "instrument")
        effect_modifiers = _column_names(spec, "effect_modifiers")
        adjustment_set = _column_names(spec, "adjustment_set")

        if not instruments:
            raise ValueError("hte_iv 需要 spec.instrument")
        if not effect_modifiers:
            raise ValueError("hte_iv 需要 spec.effect_modifiers（CATE 的协变量集 X）")

        y = data[outcome].to_numpy().ravel().astype(int)
        t = data[treatment].to_numpy().ravel().astype(int)
        z = data[instruments]
        x = data[effect_modifiers].astype(float).to_numpy()
        w = data[adjustment_set].astype(float).to_numpy() if adjustment_set else None

        discrete_instrument = all(_is_binary(z.loc[:, column]) for column in z.columns)

        if backend == "dmliv":
            values = self._fit_dmliv(y, t, z, x, w, spec, seed, discrete_instrument)
        else:
            values = self._fit_ivforest(y, t, z, x, w, spec, seed, adjustment_set)

        values.update(
            {
                "res:sample.n": int(len(data)),
                "res:sample.n_treated": int(t.sum()),
                "res:sample.n_control": int(len(t) - t.sum()),
                "res:sample.treatment_rate": float(t.mean()),
                "res:sample.outcome_rate": float(y.mean()),
                "res:instrument.kind": "binary" if discrete_instrument else "continuous",
                "res:instrument.n_columns": len(instruments),
                "res:design.n_effect_modifiers": len(effect_modifiers),
                "res:design.n_adjustment_covariates": len(adjustment_set),
                "res:estimation.estimator": backend,
            }
        )
        return Result(family=self.id, seed=seed, values=values)

    # ---- 后端一：NonParamDMLIV（与研究代码最终版一致）----

    def _fit_dmliv(self, y, t, z, x, w, spec: Spec, seed: int, discrete_instrument: bool):
        model_final = RandomForestRegressor(
            n_estimators=spec.param("n_estimators", 300),
            max_depth=spec.param("max_depth", 5),
            min_samples_leaf=spec.param("min_samples_leaf", 30),
            max_features=spec.param("max_features", "sqrt"),
            n_jobs=spec.param("model_n_jobs", 1),
            random_state=seed,
        )
        estimator = NonParamDMLIV(
            model_y_xw="auto",
            model_t_xw="auto",
            model_t_xwz="auto",
            model_final=model_final,
            discrete_outcome=True,
            discrete_treatment=True,
            discrete_instrument=discrete_instrument,
            cv=spec.param("cv", 5),
            random_state=seed,
        )
        # bootstrap 的默认 100 次重抽样 × n_jobs=-1 会把内存打爆（实测被 SIGKILL）。
        # 显式给出重抽样次数与并行度，两者都可从 spec 覆盖。
        # percentile bootstrap 区间要可信，重抽样次数不能少。默认 200——慢，
        # 但慢是这条路的真实代价，不该靠调低次数来掩盖。低于 100 时在 Result 里
        # 打标记，让报告能把这件事摆出来。
        n_bootstrap = int(spec.param("n_bootstrap_samples", DEFAULT_BOOTSTRAP_SAMPLES))
        estimator.fit(
            Y=y,
            T=t,
            Z=z,
            X=x,
            W=w,
            inference=BootstrapInference(
                n_bootstrap_samples=n_bootstrap,
                n_jobs=spec.param("bootstrap_n_jobs", 1),
            ),
        )

        cate = estimator.effect(X=x, T0=0, T1=1).ravel()
        lower, upper = estimator.effect_interval(X=x, T0=0, T1=1, alpha=0.05)
        ate_lower, ate_upper = estimator.ate_interval(X=x, alpha=0.05)

        values: dict[str, float | int | str] = {
            "res:primary.ate": _scalar(estimator.ate(X=x)),
            "res:primary.ate_ci_lower": _scalar(ate_lower),
            "res:primary.ate_ci_upper": _scalar(ate_upper),
            "res:cate.ci_method": "bootstrap",
            "res:primary.ate_ci_method": "bootstrap",
            "res:estimation.n_bootstrap_samples": n_bootstrap,
            "res:estimation.bootstrap_adequate": "yes" if n_bootstrap >= 100 else "no",
            "res:estimation.n_estimators": int(spec.param("n_estimators", 300)),
        }
        values.update(self._cate_addresses(cate, np.ravel(lower), np.ravel(upper)))
        return values

    # ---- 后端二：CausalIVForest（解析区间，便宜）----

    @staticmethod
    def _build_forest(spec: Spec, seed: int, n_estimators: int, subforest_size: int):
        return CausalIVForest(
            n_estimators=n_estimators,
            criterion=spec.param("criterion", "het"),
            min_samples_leaf=spec.param("min_samples_leaf", 10),
            min_var_fraction_leaf=spec.param("min_var_fraction_leaf", 0.05),
            honest=True,
            inference=True,
            subforest_size=subforest_size,
            n_jobs=spec.param("model_n_jobs", 1),
            random_state=seed,
        )

    def _bootstrap_ate_interval(
        self, x, t, y, z_values, spec: Spec, seed: int, n_estimators: int, subforest_size: int
    ) -> tuple[float, float]:
        """单位层面 bootstrap 出 ATE 的 percentile 区间。

        每一轮对观测重抽样、重拟合森林，然后在**原始 X** 上预测并取均值——
        估计对象始终是原样本协变量分布下的 ATE。

        为什么不用森林自己的方差：``predict_and_var``、``prediction_stderr`` 等接口
        给的都是**逐点**方差（``predict_and_var`` 那个协方差矩阵是单点上各输出维之间的，
        不是不同 x 之间的）。同一片森林给出的各点估计高度相关，把逐点方差平均
        再除以 n 等于假设它们独立，那是错的。econml.grf 没有跨样本平均的方差接口。

        重抽样次数由 ``n_bootstrap_samples`` 控制（两个后端共用），并行度由
        ``bootstrap_n_jobs`` 控制。下标先一次性抽好再并行，所以并行度不影响结果，
        seed 固定就能复现。
        """
        n_bootstrap = int(spec.param("n_bootstrap_samples", DEFAULT_BOOTSTRAP_SAMPLES))
        rng = np.random.default_rng(seed)
        n = len(y)
        # 先把全部重抽样下标抽好，再并行——这样并行度不影响结果，seed 固定即可复现。
        indices = [rng.integers(0, n, n) for _ in range(n_bootstrap)]

        def one_replicate(rep: int, idx: np.ndarray) -> float:
            forest = self._build_forest(spec, seed + rep + 1, n_estimators, subforest_size)
            forest.fit(X=x[idx], T=t[idx], y=y[idx], Z=z_values[idx])
            return float(np.mean(np.ravel(forest.predict(x))))

        # Parallel 的返回类型 joblib 标不出来，显式收成 ndarray。
        ates = np.asarray(
            Parallel(n_jobs=spec.param("bootstrap_n_jobs", 1))(
                delayed(one_replicate)(rep, idx) for rep, idx in enumerate(indices)
            ),
            dtype=float,
        )
        # percentile 法：取重抽样分布的分位数。与 dmliv（EconML 的 BootstrapInference）
        # 保持一致。注意它**不保证**包住点估计——honest 森林向均值收缩，重抽样分布
        # 相对 θ̂ 可以有系统偏移。要以 θ̂ 为中心得改用 basic/反分位法，那是另一个选择，
        # 需要时通过 spec 暴露，不在这里悄悄换。
        lower, upper = np.percentile(ates, [2.5, 97.5])
        return float(lower), float(upper)

    def _fit_ivforest(self, y, t, z, x, w, spec: Spec, seed: int, adjustment_set: list[str]):
        if adjustment_set:
            raise ValueError(
                "ivforest 后端不接受 adjustment_set：CausalIVForest 没有独立的 W 通道，"
                "只调整 X。要么把这些变量并入 effect_modifiers 并确认这一改动，"
                "要么改用 estimator=dmliv。"
            )
        if z.shape[1] != 1:
            raise ValueError(f"ivforest 后端只支持单个 instrument，收到 {z.shape[1]} 个")

        # GRF 的 honest 方差估计把森林切成大小为 subforest_size 的子森林，
        # 因此 n_estimators 必须整除。早点说清楚，别把 econml 的原话转手给用户。
        subforest_size = int(spec.param("subforest_size", 4))
        n_estimators = int(spec.param("n_estimators", 300))
        if n_estimators % subforest_size:
            raise ValueError(
                f"ivforest 的 n_estimators（{n_estimators}）必须能被 subforest_size"
                f"（{subforest_size}）整除——GRF 的方差估计按子森林分组。"
                f"改成 {n_estimators - n_estimators % subforest_size}"
                f" 或 {n_estimators + subforest_size - n_estimators % subforest_size}。"
            )

        z_values = z.to_numpy().ravel()
        forest = self._build_forest(spec, seed, n_estimators, subforest_size)
        forest.fit(X=x, T=t, y=y, Z=z_values)

        cate = np.ravel(forest.predict(x))
        interval = forest.predict_interval(x, alpha=0.05)
        lower, upper = np.ravel(interval[0]), np.ravel(interval[1])

        n_bootstrap = int(spec.param("n_bootstrap_samples", DEFAULT_BOOTSTRAP_SAMPLES))
        ate_lower, ate_upper = self._bootstrap_ate_interval(
            x, t, y, z_values, spec, seed, n_estimators, subforest_size
        )

        values: dict[str, float | int | str] = {
            "res:primary.ate": float(np.mean(cate)),
            "res:primary.ate_ci_lower": ate_lower,
            "res:primary.ate_ci_upper": ate_upper,
            # CATE 与 ATE 的区间来自不同机制，分开记，报告里要分别说明。
            "res:cate.ci_method": "grf_honest",
            "res:primary.ate_ci_method": "forest_bootstrap",
            "res:estimation.n_bootstrap_samples": n_bootstrap,
            "res:estimation.bootstrap_adequate": "yes" if n_bootstrap >= 100 else "no",
            "res:estimation.n_estimators": n_estimators,
        }
        values.update(self._cate_addresses(cate, lower, upper))
        return values

    # ---- 共用 ----

    @staticmethod
    def _cate_addresses(cate, lower, upper) -> dict[str, float | int | str]:
        values: dict[str, float | int | str] = dict(_distribution("res:cate", cate))
        # 个体层面的显著性：CI 整体落在 0 一侧才算。这是研究代码里
        # 「significant benefitial patients」那一步的地址化版本。
        values["res:cate.n_significant_benefit"] = int(np.sum(upper < 0))
        values["res:cate.n_significant_harm"] = int(np.sum(lower > 0))
        values["res:cate.ci_width_median"] = float(np.median(upper - lower))
        return values


register(HteIv())
