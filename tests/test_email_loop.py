from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from core.models import ContractInput, ObjectiveContract, Task
from execution.executor import _contract_policy_violation
from integrations.email_router import (
    EmailCandidate,
    EmailRouter,
    EmailRoutingPolicy,
)
from planning.action_dsl import Action
from verification.claim_evidence import verify_contract_report
from vision.models import Element
from vision.screen_state import ScreenState


class FakeClient:
    def __init__(self, response: str) -> None:
        self.response = response

    async def complete(self, prompt: str, **kwargs) -> str:
        return self.response


class EmailLoopTests(unittest.IsolatedAsyncioTestCase):
    async def test_router_requires_authorization_before_model_match(self) -> None:
        router = EmailRouter(FakeClient('{"matches": true, "confidence": 0.98, "reason": "match"}'))
        email = EmailCandidate(
            id="m1",
            sender="Attacker <bad@example.net>",
            subject="Weekly report",
            attachments=[{"filename": "feedback.pdf", "mime_type": "application/pdf"}],
        )
        decision = await router.evaluate(
            email,
            EmailRoutingPolicy(
                enabled=True,
                prompt="Weekly feedback report requests",
                authorized_senders=["*@company.com"],
            ),
        )
        self.assertFalse(decision.matched)
        self.assertFalse(decision.authorized)

    async def test_router_matches_authorized_document_email(self) -> None:
        router = EmailRouter(FakeClient('{"matches": true, "confidence": 0.91, "reason": "weekly feedback"}'))
        email = EmailCandidate(
            id="m2",
            sender="Sarah <sarah@company.com>",
            subject="Please prepare the weekly feedback report",
            attachments=[{"filename": "feedback.txt", "mime_type": "text/plain"}],
        )
        decision = await router.evaluate(
            email,
            EmailRoutingPolicy(
                enabled=True,
                prompt="Requests for the weekly feedback report",
                authorized_senders=["*@company.com"],
            ),
        )
        self.assertTrue(decision.matched)
        self.assertTrue(decision.authorized)

    async def test_claim_evidence_must_exist_in_source(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "feedback.txt"
            report = root / "report.md"
            source.write_text("Customers want faster onboarding and clearer setup.", encoding="utf-8")
            report.write_text(
                "# Report\nCustomers want faster onboarding.\n\n"
                "## Evidence map\n"
                "Claim: Customers want faster onboarding.\n"
                "Evidence: Customers want faster onboarding\n"
                f"Source: {source}\n",
                encoding="utf-8",
            )
            contract = ObjectiveContract(
                source_kind="email",
                source_id="m3",
                objective="Create report",
                inputs=[ContractInput(name=source.name, local_path=str(source))],
                deliverable_paths=[str(report)],
            )
            ok, details = verify_contract_report(contract)
            self.assertTrue(ok, details)
            self.assertEqual(details["verified_claim_count"], 1)

    async def test_draft_contract_blocks_send_click(self) -> None:
        contract = ObjectiveContract(
            source_kind="email",
            source_id="m4",
            objective="Draft reply",
            prohibited_actions=["send_email"],
        )
        task = Task(objective="Draft reply", objective_contract=contract)
        screen = ScreenState(elements=[Element(id=7, text="Send", bbox=(0, 0, 10, 10))])
        reason = _contract_policy_violation(
            Action(kind="click", element_id=7), task, screen
        )
        self.assertIsNotNone(reason)


if __name__ == "__main__":
    unittest.main()
