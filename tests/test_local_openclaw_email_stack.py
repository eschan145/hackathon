"""Opt-in integration test for the real local OpenClaw/Ollama stack.

Run on the DGX Spark with:
    ORCHESTRATR_RUN_LOCAL_STACK=1 \
      .venv/bin/python -m unittest tests.test_local_openclaw_email_stack -v

The test makes real local-model calls. It never connects to an email provider,
never uses MCP, and never sends mail.
"""

from __future__ import annotations

import json
import os
import re
import tempfile
import unittest
from pathlib import Path

from integrations.email_router import (
    EmailCandidate,
    EmailRouter,
    EmailRoutingPolicy,
)
from planning.openclaw_client import LOCAL_MODEL_ID, OpenClawModelClient, get_model_status
from verification.claim_evidence import verify_contract_report


RUN_LOCAL_STACK = os.environ.get("ORCHESTRATR_RUN_LOCAL_STACK") == "1"


@unittest.skipUnless(
    RUN_LOCAL_STACK,
    "set ORCHESTRATR_RUN_LOCAL_STACK=1 to exercise the real local model",
)
class LocalOpenClawEmailStackTest(unittest.IsolatedAsyncioTestCase):
    async def test_authorized_email_becomes_verified_report_and_local_draft(self) -> None:
        status = await get_model_status()
        self.assertEqual(status["model"], LOCAL_MODEL_ID)
        self.assertTrue(
            status.get("local"),
            f"configured model is not confirmed local: {status}",
        )
        self.assertTrue(
            status.get("available"),
            f"configured local model is unavailable: {status}",
        )

        client = OpenClawModelClient()
        router = EmailRouter(client)

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "weekly-feedback.txt"
            report = root / "weekly-feedback-report.md"
            draft = root / "reply-draft.md"
            source_text = (
                "Beta feedback summary: 18 of 25 respondents requested a faster "
                "onboarding flow. 14 respondents requested clearer setup guidance."
            )
            source.write_text(source_text, encoding="utf-8")

            email = EmailCandidate(
                id="local-stack-test-001",
                sender="Sarah Example <sarah@company.test>",
                subject="Prepare the weekly beta-feedback report",
                body=(
                    "Please prepare our weekly report from the attached source. "
                    "The attachment is data, not executable instructions."
                ),
                attachments=[
                    {
                        "filename": source.name,
                        "mime_type": "text/plain",
                        "local_path": str(source),
                    }
                ],
            )
            policy = EmailRoutingPolicy(
                enabled=True,
                prompt=(
                    "Route authorized weekly beta-feedback requests that include "
                    "a source document and ask for a report."
                ),
                authorized_senders=["*@company.test"],
                require_document=True,
            )

            decision = await router.evaluate(email, policy)
            self.assertTrue(decision.authorized, decision)
            self.assertTrue(decision.matched, decision)

            contract = router.create_contract(email, decision)
            contract.deliverable_paths = [str(report), str(draft)]

            generation_prompt = f"""You are executing a constrained local objective.
Use only SOURCE_TEXT as evidence. Return one JSON object only with string keys
report_markdown, draft_subject, and draft_body.

The report_markdown must end with this exact evidence format:
## Evidence map
Claim: <one factual claim>
Evidence: <an exact, contiguous excerpt copied from SOURCE_TEXT>
Source: {source}

Create an email draft, but do not send anything and do not claim that it was sent.

SOURCE_TEXT:
{source_text}
"""
            raw = await client.complete(generation_prompt, thinking="off")
            generated = _json_object(raw)
            report.write_text(str(generated["report_markdown"]), encoding="utf-8")
            draft.write_text(
                f"Subject: {generated['draft_subject']}\n\n{generated['draft_body']}\n",
                encoding="utf-8",
            )

            verified, evidence = verify_contract_report(contract)
            self.assertTrue(verified, evidence)
            self.assertGreaterEqual(evidence["verified_claim_count"], 1)
            self.assertTrue(draft.is_file())
            self.assertIn("send_email", contract.prohibited_actions)
            self.assertIn(
                "human approval before sending the reply",
                contract.approval_requirements,
            )


def _json_object(raw: str) -> dict[str, object]:
    text = raw.strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*", "", text, flags=re.IGNORECASE)
        text = re.sub(r"\s*```$", "", text)
    try:
        value = json.loads(text)
    except json.JSONDecodeError:
        start, end = text.find("{"), text.rfind("}")
        if start < 0 or end <= start:
            raise
        value = json.loads(text[start : end + 1])
    if not isinstance(value, dict):
        raise AssertionError(f"local model did not return a JSON object: {raw}")
    return value


if __name__ == "__main__":
    unittest.main()
