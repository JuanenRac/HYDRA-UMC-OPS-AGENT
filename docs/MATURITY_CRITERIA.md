<!-- =============================================================================
HYDRA-UMC-OPS-AGENT - Maturity exit criteria
Copyright (C) 2026 JuanenRac (Electro Hobby 3D) <electrohobby3d@gmail.com>
GPL-3.0 - see LICENSE
============================================================================= -->

# Exit Criteria: Scaffolding to Functional

A project is `scaffolding` until every item below is true and verifiable in
the repository (a test, a CI check or a reproducible command) - not when the
code merely exists. This project is labelled `functional`, and the evidence is:

- [x] The API accepts only signed, approved and reversible plans. A deploy
  verifies an Ed25519 signature over the exact diff, project, expiry and
  commit (`tests/test_signed_approvals.py`), and a promotion can be undone
  (`rollback`, automatic rollback on a failed health check).
- [x] Read, propose and execute are separate permissions, each enforced and
  tested. Approving needs the approver's private key, executing needs the
  registry of public keys, reading and proposing need neither; an approval
  made by editing the file is refused (`tests/test_signed_approvals.py`).
  These are cryptographic permissions: they do not stop a user who owns the
  checkout from running the commands.
- [x] Every executed change leaves an audit record and a rollback path. A
  deploy that cannot write its start record does not happen, the journal is
  hash-chained (`control audit-verify`), and the previous checkout is kept.

Verified on real hardware or services is a separate, later step: a passing
software check does not certify physical behaviour.
