"""dynamic_lag_dml: the lag profile of one treatment period on per-period outcomes.

The estimand is ``theta_0 ... theta_K``: what one period of treatment does to the outcome
of that period and to the outcomes of the periods after it, on panel data whose
trajectories end at times that depend on the state and the treatment. Three ingredients,
each shown necessary by the author's ablations: adjustment on the state at the treatment
period, sequential peeling so each lag becomes one partially linear problem, and
inverse-probability-of-continuation weighting for the informative horizon.

Read family.yaml before the code. Two things there are easy to get wrong and expensive:
the Stage-1 nuisances carry the IPCW weights (unweighted they target a different
function), and the moment is not orthogonal in the continuation model, so that one
nuisance needs a flexible learner while the other two do not.

Neither interval is calibrated. Consistency of the profile is proved; a limiting
distribution is not, so results carry ``ci_calibration = "exploratory"`` and the
claim-level decision forbids calling any lag significant.
"""

from causpec.families.dynamic_lag_dml.estimator import DynamicLagDml

__all__ = ["DynamicLagDml"]
