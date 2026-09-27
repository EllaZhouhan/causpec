"""Runtime: RunContext, atomic writes, audit log, manifest.

This is where G5 (reproducibility) is enforced. Mirrors the run-directory layout of
design.md section 14.

Two rules: every write is atomic (temporary file plus rename), and **no raw rows and
no credentials reach the log**.
"""
