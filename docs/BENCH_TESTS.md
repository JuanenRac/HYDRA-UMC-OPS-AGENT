# Bench tests

Every test below is **not executed**. The edge and control sides have run only in tests and on one machine; the checks that read the health of a real Compute Module (disk space, temperature, throttling, backups) are built (`host_checks`) but have only run against stand-in readings. Write a result only after a person ran the step.

## What the software already covers (no board needed)

- The unit tests cover the signed channel (HMAC, nonce, timestamp), the canary rollout with rollback, the watchdog ingest and the outbox of events.
- The checks for free disk space, temperature, throttling and backups (`host_checks`) are covered by tests with stand-in readings; step 6 runs them on a real board.

## Setup

- One control host and two Compute Modules (or two machines) with the edge side installed from `deploy/`, each with its own node secret in a file outside the repository.
- A message broker for the events; `transport.allow_remote_deploy` stays off except in step 5.

## Steps

| # | Step | Expected result | Result |
|---|------|-----------------|--------|
| 1 | Start `edge serve` on both nodes and run `control remote health` from the control host. | Both answer, signed with their own secret. | not executed |
| 2 | Send a request with a wrong secret, an old timestamp and a repeated nonce. | Each is refused and counted. | not executed |
| 3 | Make a node fail on purpose and let the watchdog journal record it. | `edge healing-ingest` opens one incident for that node; when the node recovers it closes it. | not executed |
| 4 | Run `control remote verify` for that incident. | The check runs on the node that owns the incident, not on another. | not executed |
| 5 | Approve a harmless proposal and run `control canary-rollout` with `allow_remote_deploy` on. | The canary node takes it first; if it fails or is unreachable the change is undone on every node that took it. | not executed |
| 6 | With `host_checks.enabled`, fill the disk of a node to a high level and heat the board under load, then run `edge collect`. | The snapshot shows `hostHealth` with the real `vcgencmd` flags and the incident names the disk, the temperature or the throttling. | not executed |
| 7 | Cut the broker and cause an incident. | The event waits in the outbox file and is sent after the broker returns. | not executed |

## What this bench cannot show

Real network loss between the nodes, clock drift larger than the timestamp window and the effect of a rollout on a machine that is working.
