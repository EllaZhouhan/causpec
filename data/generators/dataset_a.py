"""合成数据集 A：带真值的 HTE-IV 结构因果模型。

对应 design.md 第 15 节。形状照着真实的 ICU 透析研究来（处理率约 9.5%、
死亡率约 4%、consultant 层级的 physician preference 工具变量），
但每个个体的真实处理效应一并输出，供 evals 计算覆盖率。

**生成的数据不入库**，只入库这个生成器。

结构
----
    U ──────────────┐            U：未观测的病情严重度
    │               ▼
    X ──────────► T ──────────► Y
    ▲               ▲
    │               │
  consultant ─────► Z            Z：主治医生的历史透析倾向（leave-one-out）

关键性质：

1. **U 同时影响 T 和 Y**，所以朴素差值和后门调整都有偏——只有 IV 能识别。
   这是数据集 A 最重要的用途：验证「调整不够」时工具能不能看出来。
2. **Z 只通过 T 影响 Y**（exclusion restriction 成立），且 Z 对 T 的影响单调
   （monotonicity 成立）。
3. **效应异质**：τ(X) 随 AKI 分期与钾离子升高而增大（病情越重获益越多）。
4. Z 可以是连续的（preference 本身）或二值的（preference 高于中位数），
   由 ``instrument_kind`` 控制——hte_iv family 两种都要支持。

真值列
------
``tau_true``        每个个体的真实处理效应（风险差 p1 - p0，由潜在结局概率直接算出）
``beta_true``       logit 尺度上的效应
``u_true``          未观测混杂的真值（只用于诊断，不给估计器）
``compliance_type`` 仅 instrument_kind="binary" 时：always/never/complier
``p0_true``/``p1_true``  两个潜在结局的真实概率
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np
import pandas as pd

# 连续协变量：名字照着真实数据来，便于把真实数据接进同一条管道。
CONTINUOUS_COVARIATES: dict[str, tuple[float, float, float, float]] = {
    # name: (mean, sd, low, high)
    "admission_age": (61.0, 15.0, 18.0, 95.0),
    "min_bicarbonate": (21.0, 4.5, 5.0, 40.0),
    "max_creatinine": (180.0, 120.0, 30.0, 900.0),
    "max_potassium": (4.6, 0.8, 2.5, 8.0),
    "min_pH": (7.33, 0.09, 6.90, 7.60),
    "max_urea": (12.0, 8.0, 1.0, 60.0),
    "min_ArterialPressure": (68.0, 13.0, 30.0, 120.0),
    "max_heartRate": (98.0, 20.0, 40.0, 180.0),
    "min_O2Saturation": (93.0, 5.0, 60.0, 100.0),
    "min_GCS_Total": (12.0, 3.5, 3.0, 15.0),
    "max_WBC": (14.0, 7.0, 1.0, 60.0),
    "min_platelet": (180.0, 90.0, 5.0, 600.0),
    "min_hemoglobin": (9.5, 2.0, 4.0, 18.0),
    "max_uo_12h_ml": (450.0, 350.0, 0.0, 3000.0),
    "min_netBodyBalancePerHour": (-20.0, 80.0, -500.0, 400.0),
}

NOISE_COVARIATES = 10  # 与 T、Y 都无关，用来检验工具会不会被噪声带偏


@dataclass
class DatasetAConfig:
    """数据集 A 的生成参数。改这里，不要改代码。"""

    n: int = 10_000
    n_consultants: int = 400
    seed: int = 20260925

    instrument_kind: str = "continuous"  # continuous | binary

    # ---- 目标边际量（生成后会校准到接近这些值）----
    target_treatment_rate: float = 0.095
    target_death_rate: float = 0.041

    # ---- 效应结构 ----
    # 效应定义在 **logit 尺度**上：logit(p1) = logit(p0) + beta(X)。
    # 不直接定义风险差，因为基线死亡率只有约 4%，风险差最多也就 -0.04——
    # 直接给风险差会被 clip 截断，真值就不再是真值了（这个 bug 由真值验证抓出）。
    #   beta(X) = base + aki * aki_stage + k * (potassium - 4.5)
    # 负数表示降低死亡风险。base 取正数，表示 AKI 0 期且钾正常的患者接受透析反而有害。
    effect_base: float = 0.45
    effect_per_aki_stage: float = -0.40
    effect_per_potassium: float = -0.55

    # ---- 未观测混杂强度 ----
    confounding_on_treatment: float = 1.10  # U → T
    confounding_on_outcome: float = 0.90  # U → Y

    # ---- 工具变量强度：consultant 偏好的离散程度 ----
    preference_sd: float = 0.9  # consultant 随机效应的 sd（logit 尺度）
    instrument_strength: float = 1.30  # Z → T 的系数

    # 效应是否随 compliance 类型变化。False 时条件 LATE == CATE，
    # 可直接用 tau_true 验证 IV 估计；True 时两者不同，工具必须说清楚
    # 估计对象只是 complier（design.md 7.6）。
    effect_varies_by_compliance: bool = False
    compliance_effect_shift: float = -0.35  # logit 尺度

    noise_covariates: int = NOISE_COVARIATES
    covariates: dict[str, tuple[float, float, float, float]] = field(
        default_factory=lambda: dict(CONTINUOUS_COVARIATES)
    )


# 两套预设。realistic 照着真实 ICU 研究的量级来，用于 demo 与质量检查；
# 但在这个量级下 IV 的统计功效极低（complier 约 8%、死亡率约 4%，Wald 的 SE
# 比真值本身还大），数值回归测试会被噪声淹没。high_power 把 complier 份额与
# 事件率提上去，专供数值 evals——它不真实，但它让「估计器对不对」这个问题
# 有确定的答案。
PRESETS: dict[str, dict[str, object]] = {
    "realistic": {},
    "high_power": {
        "n": 40_000,
        "target_treatment_rate": 0.30,
        "target_death_rate": 0.25,
        "instrument_strength": 2.20,
        "preference_sd": 1.30,
        "confounding_on_treatment": 0.80,
        "confounding_on_outcome": 0.70,
    },
}


def config_for(preset: str, **overrides: object) -> DatasetAConfig:
    """按预设名构造配置，overrides 优先。"""
    if preset not in PRESETS:
        raise ValueError(f"未知预设 {preset}，可选：{'、'.join(PRESETS)}")
    return DatasetAConfig(**{**PRESETS[preset], **overrides})  # type: ignore[arg-type]


def _truncated_normal(rng, mean, sd, low, high, n):
    """截断正态：临床变量都有生理上下界。"""
    out = rng.normal(mean, sd, n)
    return np.clip(out, low, high)


def _sigmoid(x):
    return 1.0 / (1.0 + np.exp(-x))


def _solve_intercept(linear, target_rate, lo=-30.0, hi=30.0, tol=1e-10):
    """二分求截距，使 mean(sigmoid(intercept + linear)) == target_rate。"""
    for _ in range(200):
        mid = (lo + hi) / 2
        rate = float(_sigmoid(mid + linear).mean())
        if abs(rate - target_rate) < tol:
            return mid
        if rate < target_rate:
            lo = mid
        else:
            hi = mid
    return (lo + hi) / 2


def generate(config: DatasetAConfig | None = None) -> pd.DataFrame:
    """生成数据集 A。同一个 seed 必然给出同一份数据。"""
    cfg = config or DatasetAConfig()
    if cfg.instrument_kind not in ("continuous", "binary"):
        raise ValueError(f"instrument_kind 只能是 continuous 或 binary，收到 {cfg.instrument_kind}")
    rng = np.random.default_rng(cfg.seed)
    n = cfg.n

    # ---- 1. 观测协变量 ----
    data: dict[str, np.ndarray] = {}
    for name, (mean, sd, low, high) in cfg.covariates.items():
        data[name] = _truncated_normal(rng, mean, sd, low, high, n)
    for j in range(cfg.noise_covariates):
        data[f"noise_{j:02d}"] = rng.normal(0.0, 1.0, n)

    data["gender_Male"] = rng.binomial(1, 0.58, n)
    data["admitType_EM"] = rng.binomial(1, 0.62, n)

    # AKI 分期由肌酐与尿量决定——它同时是混杂和效应修饰因子
    aki_linear = (
        0.010 * (data["max_creatinine"] - 180.0)
        - 0.0022 * (data["max_uo_12h_ml"] - 450.0)
        + rng.normal(0, 1.0, n)
    )
    data["max_aki_stage_smoothed"] = np.clip(
        np.digitize(aki_linear, [-0.6, 0.7, 1.9]), 0, 3
    ).astype(int)

    data["sofa_total_24h"] = np.clip(
        np.round(
            6.0
            + 1.4 * data["max_aki_stage_smoothed"]
            - 0.05 * (data["min_ArterialPressure"] - 68.0)
            - 0.25 * (data["min_GCS_Total"] - 12.0)
            + rng.normal(0, 2.0, n)
        ),
        0,
        24,
    ).astype(int)

    df = pd.DataFrame(data)

    # ---- 2. 未观测混杂：病情严重度里没被记录下来的那部分 ----
    u = rng.normal(0.0, 1.0, n)

    # ---- 3. consultant 与 physician preference 工具变量 ----
    # 病人随机分配给 consultant（这是 exclusion restriction 成立的关键：
    # 分配与病人特征无关，所以 consultant 的偏好不会通过别的路径影响结局）。
    consultant = rng.integers(0, cfg.n_consultants, n)
    consultant_effect = rng.normal(0.0, cfg.preference_sd, cfg.n_consultants)
    df["consultant_id"] = consultant

    # 观测到的 preference = 该 consultant 其他病人的透析率（leave-one-out），
    # 真实数据就是这么构造的，所以这里也这么造：带测量噪声的随机效应。
    n_per_consultant = np.bincount(consultant, minlength=cfg.n_consultants)
    measurement_noise = rng.normal(
        0.0, 1.0 / np.sqrt(np.maximum(n_per_consultant[consultant], 1)), n
    )
    preference_logit = consultant_effect[consultant]
    df["consultant_preference"] = _sigmoid(preference_logit - 2.2 + 0.35 * measurement_noise)

    if cfg.instrument_kind == "binary":
        z = (df["consultant_preference"] > df["consultant_preference"].median()).astype(int)
        z_for_treatment = z.to_numpy().astype(float)
    else:
        z = df["consultant_preference"]
        # 标准化后进入处理方程，让 instrument_strength 的量纲稳定
        z_for_treatment = ((z - z.mean()) / z.std()).to_numpy()
    df["instrument"] = z

    # ---- 4. 处理分配：U 有影响（混杂），Z 单调地有影响（工具有效）----
    treatment_linear = (
        0.55 * df["max_aki_stage_smoothed"]
        + 0.085 * (df["sofa_total_24h"] - 6.0)
        + 0.45 * (df["max_potassium"] - 4.6)
        - 0.085 * (df["min_bicarbonate"] - 21.0)
        + 0.0022 * (df["max_creatinine"] - 180.0)
        - 0.0009 * (df["max_uo_12h_ml"] - 450.0)
        + cfg.confounding_on_treatment * u
    ).to_numpy()

    base_linear = treatment_linear + cfg.instrument_strength * z_for_treatment
    intercept_t = _solve_intercept(base_linear, cfg.target_treatment_rate)
    p_treat = _sigmoid(intercept_t + base_linear)

    # 用同一个均匀随机数决定「若 Z 取各个值时会不会接受处理」，
    # 这样 monotonicity 按构造成立，也能直接读出 compliance 类型。
    uniform = rng.uniform(0, 1, n)
    df["isDialysisICU"] = (uniform < p_treat).astype(int)

    if cfg.instrument_kind == "binary":
        p_if_z0 = _sigmoid(intercept_t + treatment_linear + cfg.instrument_strength * 0.0)
        p_if_z1 = _sigmoid(intercept_t + treatment_linear + cfg.instrument_strength * 1.0)
        t_if_z0 = (uniform < p_if_z0).astype(int)
        t_if_z1 = (uniform < p_if_z1).astype(int)
        compliance = np.where(
            (t_if_z0 == 1) & (t_if_z1 == 1),
            "always_taker",
            np.where((t_if_z0 == 0) & (t_if_z1 == 0), "never_taker", "complier"),
        )
        df["compliance_type"] = compliance
        is_complier = compliance == "complier"
    else:
        df["compliance_type"] = "unknown"  # 连续 IV 下没有三分类
        is_complier = np.zeros(n, dtype=bool)

    # ---- 5. 处理效应：定义在 logit 尺度上，异质，只依赖观测到的 X ----
    beta = (
        cfg.effect_base
        + cfg.effect_per_aki_stage * df["max_aki_stage_smoothed"].to_numpy()
        + cfg.effect_per_potassium * (df["max_potassium"].to_numpy() - 4.5)
    )
    if cfg.effect_varies_by_compliance:
        beta = beta + cfg.compliance_effect_shift * is_complier
    df["beta_true"] = beta

    # ---- 6. 潜在结局与观测结局 ----
    outcome_linear = (
        0.30 * df["max_aki_stage_smoothed"]
        + 0.075 * (df["sofa_total_24h"] - 6.0)
        - 0.16 * (df["min_GCS_Total"] - 12.0)
        - 0.030 * (df["min_ArterialPressure"] - 68.0)
        + 0.020 * (df["max_urea"] - 12.0)
        + cfg.confounding_on_outcome * u
    ).to_numpy()
    intercept_y = _solve_intercept(outcome_linear, cfg.target_death_rate)
    logit_p0 = intercept_y + outcome_linear
    p0 = _sigmoid(logit_p0)
    p1 = _sigmoid(logit_p0 + beta)  # logit 尺度加法，天然落在 (0,1)，不需要截断
    df["p0_true"] = p0
    df["p1_true"] = p1
    # τ 是风险差，由潜在结局概率直接算出——按构造就是真值，不会被截断。
    df["tau_true"] = p1 - p0

    uniform_y = rng.uniform(0, 1, n)
    y0 = (uniform_y < p0).astype(int)
    y1 = (uniform_y < p1).astype(int)
    df["death"] = np.where(df["isDialysisICU"] == 1, y1, y0)

    df["u_true"] = u  # 未观测混杂的真值：只给诊断用，不给估计器
    df.insert(0, "unit_id", np.arange(1, n + 1))
    return df


def truth(df: pd.DataFrame) -> dict[str, float]:
    """这份数据的真值汇总，供 evals 对照。"""
    tau = df["tau_true"].to_numpy()
    treated = df["isDialysisICU"].to_numpy().astype(bool)
    death = df["death"].to_numpy()
    out = {
        "ate_true": float(np.mean(tau)),
        "att_true": float(np.mean(tau[treated])),
        "treatment_rate": float(np.mean(treated)),
        "death_rate": float(np.mean(death)),
        "naive_difference": float(np.mean(death[treated]) - np.mean(death[~treated])),
    }
    compliers = (df["compliance_type"] == "complier").to_numpy()
    if compliers.any():
        out["late_true"] = float(np.mean(tau[compliers]))
        out["complier_share"] = float(np.mean(compliers))
    return out


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="生成合成数据集 A（带真值）。")
    parser.add_argument("--out", type=Path, required=True, help="输出 CSV 路径（不入库）")
    parser.add_argument("--n", type=int, default=DatasetAConfig.n)
    parser.add_argument("--seed", type=int, default=DatasetAConfig.seed)
    parser.add_argument("--instrument-kind", choices=["continuous", "binary"], default="continuous")
    parser.add_argument(
        "--preset",
        choices=sorted(PRESETS),
        default="realistic",
        help="realistic=照真实研究量级（demo 用）；high_power=功效足够（数值 evals 用）",
    )
    parser.add_argument(
        "--vary-effect-by-compliance",
        action="store_true",
        help="让效应随 compliance 类型变化，此时条件 LATE ≠ CATE",
    )
    args = parser.parse_args(argv)

    overrides: dict[str, object] = {
        "seed": args.seed,
        "instrument_kind": args.instrument_kind,
        "effect_varies_by_compliance": args.vary_effect_by_compliance,
    }
    if args.n != DatasetAConfig.n:  # 只有显式指定时才覆盖预设的 n
        overrides["n"] = args.n
    df = generate(config_for(args.preset, **overrides))
    args.out.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(args.out, index=False)

    print(f"写入 {args.out}：{len(df):,} 行 × {df.shape[1]} 列")
    for key, value in truth(df).items():
        print(f"  {key:20} {value: .4f}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
