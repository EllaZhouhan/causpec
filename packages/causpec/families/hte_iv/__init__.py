"""hte_iv: heterogeneous treatment effects under an instrumental-variable design.

Both binary and continuous instruments are supported. Two backends, selected through
``spec.estimation.params.estimator``; see estimator.py.

A note on calibration: EconML's ``DRTester`` is built on doubly-robust scores that
assume unconfoundedness, so it **cannot be used directly in an IV setting**. An
IV-appropriate score has to be written (design.md section 9, TODO).
"""

from causpec.families.hte_iv.estimator import HteIv

__all__ = ["HteIv"]
