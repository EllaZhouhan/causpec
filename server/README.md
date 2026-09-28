# server/causpec_mcp

The local MCP server, CauSpec's **primary form** (design.md section 3). It runs on the
user's own machine, and Claude Code or Desktop connects to it.

Implemented in Phase 3 (v0.3).

## The tools (design.md section 12)

| Tool | Purpose | readOnlyHint |
|---|---|---|
| `list_sources` | List the configured data sources | yes |
| `describe_source` | Schema and column statistics, **no raw rows** | yes |
| `register_dataset` | Materialise a derived snapshot | |
| `apply_mapping` | Apply a mapping and check for schema drift | |
| `draft_spec` | Draft a spec | |
| `update_field` | Update one field's value, source and status | |
| `confirm_spec` | Compute spec_hash and record the confirmation | |
| `route_family` | Return the candidate families, the excluded ones with reasons, and the estimand reconciliation | yes |
| `run_quality_check` | Return the issue list with addresses | |
| `record_waiver` | A waiver, which must carry a reason | |
| `estimate` | Run the family once the gates pass | |
| `render_report` | Substitute placeholders and verify the claim level | |
| `list_runs` | Query the history | yes |
| `get_run` | Query one run | yes |

Tools without readOnlyHint write server state, but **no tool modifies a data source**.

## The gates (design.md 11.2)

Three conditions are checked before `estimate`; failing any returns a structured error
(code, reason, remediation):

1. `spec_hash` matches the confirmation record, and every critical field is `confirmed`
2. A quality report exists for the current `(snapshot_fingerprint, spec_hash)` with no
   unresolved blocking issues; waived issues carry a reason
3. `family.supports(spec)` passes, and `spec.estimand` is within what that family
   declares it can identify

## doctor

```bash
causpec-mcp doctor
```

Checks dependencies, data-source connectivity, and **whether the database account
genuinely cannot write**: the read-only guarantee comes from account permissions, not
from a prompt.
