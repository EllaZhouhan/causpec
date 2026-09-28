# ADR-0002: Data-source boundaries

- Status: proposed
- Date: 2026-09-22
- Related: design.md 6.1, principle 3, principle 4, 1.3 (arbitrary SQL as a non-goal)

## Context

The MCP server is the most privileged component in the system: it holds database
credentials and filesystem access, and the requests it executes come from a model.

The minimal demonstration server was written like this:

```python
rows = list(csv.DictReader(Path(arguments["data_path"]).open()))
```

**Any path is accepted.** A model can send `{"data_path": "/Users/.../real-records.csv"}`
and the server will read it.

design.md 6.1 already has `root` and `allowed_relations`, but only as configuration
fields: it does not say they are **enforced boundaries**, nor how they are enforced. In a
setting where real medical data is connected, that difference is fatal.

## Decision

Treat data-source boundaries as hard constraints on the server, written into the Phase 3
acceptance criteria.

**File sources**

1. A path must be `resolve()`d (following symlinks and `..`) and then checked to lie
   inside the configured `root`; otherwise it is refused
2. Only the extensions declared in the configuration are accepted (`.csv`, `.parquet`)
3. The structured refusal **does not echo the resolved absolute path**, that would leak
   the directory structure back into the model's context

**Database sources**

1. Only `source_id` plus `relation` are accepted; no SQL fragment of any kind
   (design.md 1.3: arbitrary SQL is a non-goal)
2. `relation` must match an entry in `allowed_relations` exactly
3. `masked_columns` are dropped in the adapter, not left to a higher layer to remember
4. `causpec-mcp doctor` actually attempts a write to confirm the account cannot write,
   and exits with an error if it can

**Both**

No tool signature contains an "arbitrary path" or "arbitrary query" parameter. The
boundary is expressed in the schema, not patched up at runtime.

## Rationale

Principle 3 says "the read-only guarantee comes from database account permissions, not
from a prompt". That holds for databases, but **there is no counterpart for file
sources**, a filesystem has no read-only account, so the server has to draw the
boundary itself. `root` is that boundary.

Recording this now rather than at Phase 3: constraints of this kind get harder to add
the later they come. Once the server is written and its tools work, adding path
validation means editing every tool entry point, and one will be missed. Written into
the acceptance criteria, it does not get skipped.

## Options rejected

**A. Write "do not access paths outside root" into SKILL.md.** That is a prompt-level
constraint and directly contradicts principle 3, whose entire point is not to rely on
prompts for a safety guarantee. Rejected.

**B. No restriction; the user is responsible for their own configuration.** This pushes
responsibility onto the person who cannot see the parameters the model sends. Rejected.

**C. Prefix matching without resolving.** One step cheaper, but it fails against
`root/../../etc/passwd` and against a symlink pointing outside. Rejected.

## Consequences

**Benefits**: file and database sources gain symmetric boundary guarantees, and
principle 3 becomes a property of the system rather than of databases.

**Costs**:

1. Every tool taking a data-source argument must go through one validation entry point
   rather than each writing its own. `core/adapters/` needs a single resolution function.
2. Not echoing the absolute path in a refusal makes debugging a configuration slightly
   harder, the error can only say "outside the permitted range", with the path visible
   in the server's stderr log.
3. `doctor` genuinely writing to the database needs a target that is clearly harmless
   (attempting to create a table in a schema that does not exist, expecting failure).
   Take care not to leave traces in a production database.

## Open questions

- May `root` hold more than one directory? (A multi-project setup might need it.)
- The upload form (skill on claude.ai) lands files in a temporary directory. Does that
  directory count as an implicit `root`?
