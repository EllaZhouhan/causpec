"""Analysis family plugins.

Each family directory holds (design.md section 5): family.yaml, spec extensions, its
own checks, an estimation adapter, figures, evals and tests.

- ``hte_iv``             heterogeneous treatment effects under an IV design
- ``hte_backdoor``       heterogeneous treatment effects under backdoor adjustment
- ``dynamic_lag_dml``    the lag profile of one treatment period, with IPCW for an
  informative horizon (not implemented)
"""
