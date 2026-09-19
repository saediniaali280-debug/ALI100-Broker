# ALI100-Broker Execution Service

Execution service for the ALI100 ecosystem.

## Pipeline
ZehnSarmaye -> signed request -> idempotency -> Risk Gate -> Ledger -> Adapter -> Evidence/Receipt -> callback -> Deal settlement.

## Modes
- DRY_RUN: never produces external effects.
- LIVE_READY: validates configuration/policy but refuses execution.
- LIVE: executes only a configured adapter and requires owner approval in the signed request.

## API
- GET /health
- POST /v1/executions

Required POST headers:
- X-ALI100-Timestamp
- X-ALI100-Signature = HMAC-SHA256(timestamp + "." + raw_body)

Required request fields:
- request_id
- idempotency_key
- deal_id
- amount (integer, non-negative)

## Environment
ALI100_SHARED_SECRET
ALI100_MODE=DRY_RUN|LIVE_READY|LIVE
ALI100_LEDGER_DB
ALI100_MAX_AMOUNT
ALI100_REPLAY_WINDOW_SEC
ALI100_ADAPTER_WEBHOOK_URL
ALI100_CALLBACK_URL
PORT

No bank/payment provider is bundled into the core. Payment is an adapter.
