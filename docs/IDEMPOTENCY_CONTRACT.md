# Idempotency contract

The Broker binds each idempotency key to the canonical request payload stored with the original execution.

- Replaying the same key with the same payload returns the original request ID and stored state.
- A replay reports `ok: true` only when the original execution state is `COMPLETED`.
- Reusing a key with a different canonical payload returns `idempotency_key_conflict`; it never starts a second adapter call.
- The initial claim uses `INSERT OR IGNORE` and checks the affected-row count before any adapter call. A concurrent loser reads the existing claim or returns `execution_claim_conflict` when no claim can be confirmed.
- A pending or failed execution is not converted into success by replay.

The unit tests use isolated temporary SQLite databases. They do not call a live adapter or perform an external transaction.