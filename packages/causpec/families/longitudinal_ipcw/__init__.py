"""longitudinal_ipcw: longitudinal treatment effects via IPCW. **Not implemented.**

The spec structure follows the seven components of a target trial, plus event_roles,
which assigns death, discharge, transfer and similar events explicitly to outcome,
competing, censoring or terminal (design.md 7.3).

Blocked on a prerequisite: references/longitudinal-ipcw.md has to state how each
event is handled and how the resulting estimand should be read (design.md 7.3, TODO).
Code follows that document, not the other way round.
"""
