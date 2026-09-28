"""dynamic_lag_dml: the lag profile of one treatment period on per-period outcomes.

**Not implemented yet**; family.yaml is the declaration the code will follow.

The estimand is the profile ``theta_0 ... theta_K``: what one period of treatment does
to the outcome of that period and to the outcomes of the periods after it, on panel data
whose trajectories end at times that depend on the state and the treatment. Three
ingredients, each of which the author's simulations show is necessary: adjustment on the
state at the treatment period, sequential peeling so each lag becomes one partially
linear problem, and inverse-probability-of-continuation weighting for the informative
horizon.

Read family.yaml before the code. Two things there are easy to get wrong and expensive:
the Stage-1 nuisances carry the IPCW weights (unweighted they target a different
function), and the moment is not orthogonal in the continuation model, so that one
nuisance needs a flexible learner while the other two do not.
"""
