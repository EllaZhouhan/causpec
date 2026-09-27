"""Cross-family data-quality and identifiability checks.

Mirrors the four layers of design.md section 8:

| Layer          | Checks                                                           |
|----------------|------------------------------------------------------------------|
| basic          | types, ranges, uniqueness, missingness, NULL-encoding variants     |
| temporal       | treatment before time zero, outcome before treatment, short follow-up |
| identification | prevalence, overlap, SMD, suspected post-treatment, instrument relevance |
| feasibility    | per-arm sample sizes, event counts, minimum subgroup n, extreme weights and ESS |

Each check has an address ``qc:<check_id>`` for the report to cite. Repairs act on
the derived snapshot only.

Family-specific checks live with their family; this package is for the ones that
apply regardless of design. Not implemented yet — see plan.md Phase 1 tasks 4 and 5.
"""
