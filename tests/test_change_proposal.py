# =============================================================================
# HYDRA-UMC-OPS-AGENT - tests/test_change_proposal.py
# Copyright (C) 2026 JuanenRac (Electro Hobby 3D) <electrohobby3d@gmail.com>
# GPL-3.0 - see LICENSE
# =============================================================================
import tempfile
import unittest
from pathlib import Path

from hydra_umc_ops_agent.change_proposal import (
    STATUS_APPROVED,
    STATUS_PENDING,
    STATUS_REJECTED,
    ChangeProposalError,
    InvalidDiffError,
    InvalidTransitionError,
    ProposalLoadError,
    SecretShapedDiffError,
    approve_change,
    load_proposal,
    propose_change,
    reject_change,
    save_proposal,
)

_REAL_DIFF = (
    "--- a/config.json\n"
    "+++ b/config.json\n"
    "@@ -1,3 +1,3 @@\n"
    " {\n"
    '-  \"retries\": 0\n'
    '+  \"retries\": 3\n'
    " }\n"
)


def _make_proposal(**overrides):
    kwargs = dict(
        incident_id="inc-1",
        correlation_id="corr-1",
        project_name="HYDRA-UMC-SERVER",
        description="Increase retry count to 3",
        diff=_REAL_DIFF,
        rationale="The service gives up too early on a transient network blip",
    )
    kwargs.update(overrides)
    return propose_change(**kwargs)


class ProposeChangeTests(unittest.TestCase):
    def test_a_real_proposal_starts_pending(self):
        proposal = _make_proposal()
        self.assertEqual(proposal.status, STATUS_PENDING)
        self.assertIsNone(proposal.decided_by)

    def test_rejects_a_diff_that_does_not_look_like_a_real_unified_diff(self):
        with self.assertRaises(InvalidDiffError):
            _make_proposal(diff="just some plain text, not a diff at all")

    def test_rejects_an_empty_diff(self):
        with self.assertRaises(InvalidDiffError):
            _make_proposal(diff="   ")

    def test_rejects_an_empty_rationale(self):
        with self.assertRaises(ChangeProposalError):
            _make_proposal(rationale="")


class ApproveRejectTests(unittest.TestCase):
    def test_approve_transitions_to_approved_with_a_real_approver(self):
        proposal = _make_proposal()
        approved = approve_change(proposal, approved_by="Juan Enrique")
        self.assertEqual(approved.status, STATUS_APPROVED)
        self.assertEqual(approved.decided_by, "Juan Enrique")
        self.assertIsNotNone(approved.decided_at)
        # the original object is untouched - immutability is real, not just documented
        self.assertEqual(proposal.status, STATUS_PENDING)

    def test_approve_requires_a_real_non_empty_approver(self):
        proposal = _make_proposal()
        with self.assertRaises(ChangeProposalError):
            approve_change(proposal, approved_by="   ")

    def test_approve_stamps_a_real_content_digest(self):
        approved = approve_change(_make_proposal(), approved_by="Juan Enrique")
        self.assertIsNotNone(approved.approved_content_digest)
        approved.verify_approval_content()  # must not raise

    def test_editing_the_diff_after_approval_invalidates_it(self):
        # V07-003 (P1): the
        # review pass's own exact reproduction - a saved, approved proposal
        # file is real, mutable JSON on disk. Editing its diff (or
        # project) after approval while leaving status: "approved"
        # untouched used to let deploy_canary() apply completely
        # different content than what was actually reviewed.
        from dataclasses import replace as _replace
        approved = approve_change(_make_proposal(), approved_by="Juan Enrique")
        tampered = _replace(approved, diff=_REAL_DIFF.replace("3", "999"))
        with self.assertRaises(ChangeProposalError):
            tampered.verify_approval_content()

    def test_editing_the_project_name_after_approval_invalidates_it(self):
        from dataclasses import replace as _replace
        approved = approve_change(_make_proposal(), approved_by="Juan Enrique")
        tampered = _replace(approved, project_name="A-COMPLETELY-DIFFERENT-PROJECT")
        with self.assertRaises(ChangeProposalError):
            tampered.verify_approval_content()

    def test_a_pending_or_rejected_proposal_is_not_this_checks_concern(self):
        # verify_approval_content() only guards approved proposals -
        # ChangeNotApprovedError already owns "not approved at all".
        _make_proposal().verify_approval_content()  # pending - must not raise

    def test_cannot_approve_an_already_approved_proposal(self):
        proposal = approve_change(_make_proposal(), approved_by="A")
        with self.assertRaises(InvalidTransitionError):
            approve_change(proposal, approved_by="B")

    def test_reject_transitions_to_rejected_with_a_real_reason(self):
        proposal = _make_proposal()
        rejected = reject_change(proposal, rejected_by="Juan Enrique", reason="risk too high without more evidence")
        self.assertEqual(rejected.status, STATUS_REJECTED)
        self.assertEqual(rejected.decision_reason, "risk too high without more evidence")

    def test_reject_requires_a_real_reason(self):
        with self.assertRaises(ChangeProposalError):
            reject_change(_make_proposal(), rejected_by="A", reason="")

    def test_cannot_reject_an_already_rejected_proposal(self):
        proposal = reject_change(_make_proposal(), rejected_by="A", reason="no")
        with self.assertRaises(InvalidTransitionError):
            reject_change(proposal, rejected_by="B", reason="still no")

    def test_cannot_reject_an_already_approved_proposal(self):
        proposal = approve_change(_make_proposal(), approved_by="A")
        with self.assertRaises(InvalidTransitionError):
            reject_change(proposal, rejected_by="B", reason="changed my mind")


class SerializationTests(unittest.TestCase):
    def test_round_trip_to_dict_from_dict(self):
        proposal = approve_change(_make_proposal(), approved_by="Juan")
        restored = type(proposal).from_dict(proposal.to_dict())
        self.assertEqual(restored, proposal)

    def test_a_secret_shape_in_the_diff_is_refused_at_proposal_time(self):
        # V07-005 (P1): this
        # test used to assert that to_dict() REDACTED a secret-shaped
        # diff on serialization - but that redaction is exactly the bug:
        # save_proposal()/load_proposal() round-trip through to_dict(),
        # and canary_deploy.py's own _apply_diff() later runs `git
        # apply` on whatever `.diff` comes back out, so a "redacted"
        # save silently changed the bytes of an already-reviewed patch.
        # The diff must now be refused at proposal time instead, before
        # anything is ever stored under that (wrong) assumption.
        with self.assertRaises(SecretShapedDiffError):
            _make_proposal(diff=_REAL_DIFF + "\n# DB_PASSWORD=hunter2\n")

    def test_the_diff_survives_a_real_save_load_round_trip_byte_for_byte(self):
        # V07-005: `diff` is the immutable, applicable artifact -
        # to_dict() must never mutate it, even when it contains
        # something that merely LOOKS secret-shaped inside a value that
        # already passed the refusal above (a real, ordinary diff hunk
        # can legitimately contain the substring "password" without
        # being secret-shaped itself).
        proposal = _make_proposal(diff=_REAL_DIFF)
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "proposal.json"
            save_proposal(proposal, path)
            loaded = load_proposal(path)
        self.assertEqual(loaded.diff, proposal.diff)

    def test_save_and_load_a_proposal_file_round_trips(self):
        proposal = _make_proposal()
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "proposal.json"
            save_proposal(proposal, path)
            loaded = load_proposal(path)
        self.assertEqual(loaded.proposal_id, proposal.proposal_id)
        self.assertEqual(loaded.status, STATUS_PENDING)

    def test_loading_a_missing_file_raises_a_distinct_error(self):
        with self.assertRaises(ProposalLoadError):
            load_proposal(Path("/does/not/exist/proposal.json"))

    def test_loading_malformed_json_raises_a_distinct_error(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "bad.json"
            path.write_text("{not json", encoding="utf-8")
            with self.assertRaises(ProposalLoadError):
                load_proposal(path)


if __name__ == "__main__":
    unittest.main()
