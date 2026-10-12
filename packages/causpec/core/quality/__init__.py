"""Cross-family data-quality and identifiability checks.

Mirrors the four layers of design.md section 8:

| Layer          | Checks                                                                |
|----------------|-----------------------------------------------------------------------|
| basic          | types, uniqueness, missingness, NULL-encoding variants, zero spikes |
| temporal       | treatment before time zero, outcome before it, inversion, short follow-up |
| identification | prevalence, overlap, SMD, suspected post-treatment, instrument relevance |
| feasibility    | per-arm sizes and event counts here; weights and ESS in the families   |

Each check has an address ``qc:<check_id>`` for the report to cite. Repairs act on
the derived snapshot only.

Family-specific checks live with their family; this package is for the ones that apply
regardless of design. **The basic layer runs first and the rest are not attempted while it
blocks**: overlap, instrument relevance and continuation weights are all computed from the
numbers in these columns, so assessing identification on a table whose creatinine column
contains -999 gives a confident answer about an export convention.

Implemented here: basic, temporal, the counting half of feasibility, and the two
identification checks that need no family knowledge, both about the population. The rest of
identification lives in the families, which need to know what the instrument and the state
are, and so does the weight-and-ESS half of feasibility. A layer names what a check is about
rather than where its code lives.

The population checks run on the frame **before** the filters are applied, because the people
a filter removed are the only evidence about whether removing them mattered.

The temporal layer reads optional spec fields, and **says when it could not run**. A study
with no timestamps is a legitimate thing to analyse, but a check that reports nothing when it
had nothing to read is worse than no check: the report then reads as a clean bill of health.
"""

from causpec.core.quality.assumptions import check_assumptions, check_roles, check_routing
from causpec.core.quality.basic import analysis_columns, check_basic, config_hash, load_config
from causpec.core.quality.feasibility import check_feasibility
from causpec.core.quality.population import check_population
from causpec.core.quality.temporal import check_temporal

__all__ = [
    "analysis_columns",
    "check_assumptions",
    "check_basic",
    "check_feasibility",
    "check_population",
    "check_roles",
    "check_routing",
    "check_temporal",
    "config_hash",
    "load_config",
]
