"""Reporting: address resolution, placeholder rendering, claim-level decision.

This layer enforces G4. Prose written by the model may cite numbers only through
placeholders such as ``{{res:primary.estimate}}``; the renderer substitutes them.
**An unknown address, or a bare number anywhere in the prose, fails the render** and
the error goes back to the model to rewrite.

The claim level (causal / suggestive / associational / descriptive) is decided by
code from the diagnostics; the model may not upgrade it.
"""
