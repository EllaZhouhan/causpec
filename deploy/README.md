# deploy/

A local Postgres demo (design.md section 5, Phase 3 task 3).

`docker-compose.yml` starts a Postgres holding the relational shape of dataset B,
with a **read-only account** and views.

Key points:

- The account CauSpec connects with has `SELECT` only, and only on the views listed in
  `allowed_relations`
- The read-only guarantee comes from account permissions, **not from a prompt**
  (design.md principle 3)
- `causpec-mcp doctor` verifies this by actually attempting a write

Snapshot retention, disk encryption and capacity limits belong to the deployment
environment; CauSpec does not implement them.
