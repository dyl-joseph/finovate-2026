import unittest
from decimal import Decimal

from finovate_pipeline.financial import (
    AccountSnapshot,
    FinancialContext,
    FinancialContextVerifier,
    FindingKind,
    Recipient,
    Transaction,
    TransferIntent,
    parse_money,
)
from finovate_pipeline.intelligence import TranscriptIntelligence
from finovate_pipeline.models import Transcript, TranscriptTurn


class FinancialContractTests(unittest.TestCase):
    def test_parses_currency(self) -> None:
        self.assertEqual(parse_money("$2,000"), Decimal("2000.00"))

    def test_rejects_unknown_primary_account(self) -> None:
        with self.assertRaisesRegex(ValueError, "primary_account_id"):
            FinancialContext(
                customer_id="customer-1",
                primary_account_id="missing",
                accounts=(AccountSnapshot("checking", Decimal("100.00")),),
            )


class FinancialVerifierTests(unittest.TestCase):
    def setUp(self) -> None:
        self.verifier = FinancialContextVerifier()
        self.analyzer = TranscriptIntelligence()

    def _context(self, transaction_amount: str | None = None) -> FinancialContext:
        transactions = (
            (Transaction("txn-1", parse_money(transaction_amount), "Merchant"),)
            if transaction_amount is not None
            else ()
        )
        return FinancialContext(
            customer_id="customer-1",
            primary_account_id="checking-1",
            accounts=(
                AccountSnapshot(
                    account_id="checking-1",
                    available_balance=Decimal("2500.00"),
                    transactions=transactions,
                    recipients=(Recipient("known-1", "Landlord", 5),),
                ),
            ),
        )

    def test_flags_claimed_transaction_that_does_not_exist(self) -> None:
        analysis = self.analyzer.analyze(
            Transcript(
                "call-1",
                (TranscriptTurn("caller", "There was a charge for $900.", 0, 900),),
                caller_speaker_id="caller",
            )
        )

        findings = self.verifier.verify(analysis, self._context())

        self.assertEqual(len(findings), 1)
        self.assertEqual(
            findings[0].kind, FindingKind.CLAIMED_TRANSACTION_NOT_FOUND
        )
        self.assertEqual(findings[0].attributes["claimed_amount"], "900.00")

    def test_accepts_matching_pending_or_posted_transaction(self) -> None:
        analysis = self.analyzer.analyze(
            Transcript(
                "call-2",
                (TranscriptTurn("caller", "There was a charge for $900.", 0, 900),),
                caller_speaker_id="caller",
            )
        )

        findings = self.verifier.verify(analysis, self._context("900.00"))

        self.assertEqual(findings, ())

    def test_flags_new_recipient_and_large_transfer(self) -> None:
        analysis = self.analyzer.analyze(
            Transcript(
                "call-3",
                (TranscriptTurn("caller", "Move $2,000 to an account.", 0, 900),),
                caller_speaker_id="caller",
            )
        )
        original = self._context()
        context = FinancialContext(
            customer_id=original.customer_id,
            primary_account_id=original.primary_account_id,
            accounts=original.accounts,
            transfer_intent=TransferIntent(
                Decimal("2000.00"), "new-recipient", "Secure Account"
            ),
        )

        findings = self.verifier.verify(analysis, context)
        kinds = {finding.kind for finding in findings}

        self.assertEqual(
            kinds,
            {FindingKind.NEW_RECIPIENT, FindingKind.LARGE_TRANSFER},
        )
