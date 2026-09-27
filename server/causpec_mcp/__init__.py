"""causpec-mcp: the local MCP server (the primary form).

Mirrors design.md section 12. The server is a thin shell: parse arguments, run the
gates, call into the causpec library, return structuredContent. Every computation
lives in packages/causpec/, not here.

Relative to the skill form it provides three guarantees the skill cannot:

1. Database credentials are held by the server process, and the read-only guarantee
   comes from account permissions rather than a prompt (principle 3)
2. The gates are code, so the model cannot route around them (11.2)
3. Raw rows never enter the model's context (principle 4)

Implementation notes:

- Use the official MCP Python SDK
- Tools that change nothing declare readOnlyHint; no tool modifies a data source
- Declare outputSchema on returns and supply structuredContent
- Under stdio, logs go to stderr only
- ``causpec-mcp doctor``: check dependencies, connectivity, and that the database
  account genuinely cannot write

Phase 3 tasks 1 and 2.
"""
