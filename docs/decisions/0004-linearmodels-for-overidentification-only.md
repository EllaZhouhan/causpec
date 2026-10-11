# ADR-0004: linearmodels, for the overidentification test only

- Status: accepted
- Date: 2026-10-11
- Related: ADR-0003 (the basic layer without pandera)

## Context

ADR-0003 rejected a dependency on the grounds that the checks it offered were one pandas
call each, and that translating its output into addressed issues with repairs was most of the
work either way. One commit later `linearmodels` was added for two instrument diagnostics,
which is the same shape of decision reached the other way. The inconsistency was fair to
question, so the test from ADR-0003 was applied again, properly, by measuring.

The two statistics in question, both for `hte_iv`:

- **Endogeneity**: does the treatment behave endogenously at all? If not, the instrument's
  variance cost may be buying nothing.
- **Overidentification**: with more than one instrument, do they agree?

## Decision

Keep `linearmodels` (NCSA), and use it for **the overidentification test only**. Write the
endogeneity test here with `statsmodels`, which is already a dependency.

## Why the split

**The endogeneity test is three lines and exact.** Add the first-stage residual to the
structural equation and test its coefficient with a robust covariance. Against
`linearmodels`' `wooldridge_score` on this project's own fixture it gives 0.01333 where the
package gives 0.01324: the Wald form of the augmented regression against the score form,
asymptotically equivalent, differing only in the small-sample scaling of the robust
covariance. A test pins the agreement and that the two never differ in verdict. Nothing is
bought by importing this.

**The overidentification test failed that test in the other direction.** A hand-rolled
version, regressing the structural residual on the instruments and testing their
coefficients jointly, gave p = 0.24 where the package gives 0.092. The error is the degrees
of freedom: with k instruments and one endogenous treatment, overidentification has k - 1
degrees of freedom, not k. The hand-rolled version agreed with the package's **verdict** on
all four designs it was tried on, so a test suite built around verdicts would have passed and
the statistic would have been wrong.

The correct robust procedure (Wooldridge 2010, procedure 6.1) projects a chosen subset of the
instruments and is not a closed form with a published numerical example to check against. That
is the difference from the E-value and the first-stage F, which this project does write by
hand precisely because each can be verified against a number in a paper.

So the test from ADR-0003 holds in both cases: a package earns its place when it carries
something substantial enough to get wrong, and not otherwise.

## What was considered and rejected

- **Shea's partial R-squared**, which `linearmodels` also provides. With one endogenous
  treatment it equals the ordinary partial R-squared however many instruments are declared,
  measured as 0.1447 for all three columns at one treatment and three instruments. It differs
  only with multiple endogenous regressors, which this family does not have.
- **`statsmodels.sandbox.regression.gmm.IVGMM.jtest`**, which reproduces the
  overidentification p-value to four significant figures and needs no new dependency. Rejected
  because the `sandbox` namespace is explicitly not API-stable, and a gate that decides
  whether an analysis proceeds should not rest on an interface its own authors label
  provisional.
- **The effective F** (Montiel Olea and Pflueger), which plan.md originally asked for. No
  Python package implements it; the canonical implementations are Stata's `weakivtest` and R's
  `momentfit`. Its critical values come from simulation rather than a closed form, so it is
  not a candidate for hand-writing under this project's rule either.

## Consequences

- Four direct dependencies again: EconML, DoWhy, DoubleML, linearmodels. The surface used is
  one property, `IV2SLS(...).fit().wooldridge_overid`, which bounds how much a change in that
  package can cost.
- The overidentification check engages only with more than one instrument, so a single-
  instrument analysis, which is what the author's own application uses, never touches
  linearmodels at all.
- Both statistics describe a linear two-stage specification rather than the forest that
  produces the reported effect. The issue text says so; they are statements about the
  instruments.

## What would make this wrong

If `hte_iv` ever supports multiple endogenous treatments, Shea's partial R-squared and the
conditional first-stage F start to differ from their ordinary versions, and the case for the
dependency grows rather than shrinks. If instead the multiple-instrument path is dropped, the
overidentification check goes with it and the dependency should go too.
