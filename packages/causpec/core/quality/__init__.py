"""Cross-family data-quality and identifiability checks.

Mirrors the four layers of design.md section 8:

| Layer          | Checks                                                                |
|----------------|-----------------------------------------------------------------------|
| basic          | types, uniqueness, missingness, NULL-encoding variants (``basic.py``) |
| temporal       | treatment before time zero, outcome before treatment, short follow-up |
| identification | prevalence, overlap, SMD, suspected post-treatment, instrument relevance |
| feasibility    | per-arm sample sizes, event counts, minimum subgroup n, extreme weights and ESS |

Each check has an address ``qc:<check_id>`` for the report to cite. Repairs act on
the derived snapshot only.

Family-specific checks live with their family; this package is for the ones that apply
regardless of design. **The basic layer runs first and the rest are not attempted while it
blocks**: overlap, instrument relevance and continuation weights are all computed from the
numbers in these columns, so assessing identification on a table whose creatinine column
contains -999 gives a confident answer about an export convention.

Implemented: the basic layer. The temporal layer is still open (plan.md Phase 1 task 5); the
other two live in the families.
"""

from causpec.core.quality.basic import analysis_columns, check_basic, config_hash, load_config

__all__ = ["analysis_columns", "check_basic", "config_hash", "load_config"]
