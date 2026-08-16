"""Financial context contracts and transcript-to-account verification."""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation
from enum import StrEnum
from typing import Any

from .models import AnalysisResult, EvidenceSignal, SignalKind


def parse_money(value: str | int | float | Decimal) -> Decimal:
    """Parse an amount into a two-decimal Decimal without accepting booleans."""
    if isinstance(value, bool):
        raise ValueError("money amount cannot be a boolean")
    cleaned = str(value).replace("$", "").replace(",", "").strip()
    try:
        amount = Decimal(cleaned)
    except InvalidOperation as exc:
        raise ValueError(f"invalid money amount: {value}") from exc
    if not amount.is_finite():
        raise ValueError("money amount must be finite")
    return amount.quantize(Decimal("0.01"))


@dataclass(frozen=True, slots=True)
class Transaction:
    transaction_id: str
    amount: Decimal
    merchant: str
    status: str = "posted"

    def __post_init__(self) -> None:
        if not self.transaction_id.strip():
            raise ValueError("transaction_id cannot be empty")
        if self.amount < 0:
            raise ValueError("transaction amount cannot be negative")

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Transaction:
        return cls(
            transaction_id=str(data["transaction_id"]),
            amount=parse_money(data["amount"]),
            merchant=str(data.get("merchant", "Unknown merchant")),
            status=str(data.get("status", "posted")),
        )


@dataclass(frozen=True, slots=True)
class Recipient:
    recipient_id: str
    name: str
    previous_transfer_count: int = 0

    def __post_init__(self) -> None:
        if not self.recipient_id.strip():
            raise ValueError("recipient_id cannot be empty")
        if self.previous_transfer_count < 0:
            raise ValueError("previous_transfer_count cannot be negative")

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Recipient:
        return cls(
            recipient_id=str(data["recipient_id"]),
            name=str(data.get("name", "Unknown recipient")),
            previous_transfer_count=int(data.get("previous_transfer_count", 0)),
        )


@dataclass(frozen=True, slots=True)
class AccountSnapshot:
    account_id: str
    available_balance: Decimal
    transactions: tuple[Transaction, ...] = ()
    recipients: tuple[Recipient, ...] = ()

    def __post_init__(self) -> None:
        if not self.account_id.strip():
            raise ValueError("account_id cannot be empty")
        if self.available_balance < 0:
            raise ValueError("available_balance cannot be negative")

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> AccountSnapshot:
        return cls(
            account_id=str(data["account_id"]),
            available_balance=parse_money(data["available_balance"]),
            transactions=tuple(
                Transaction.from_dict(item) for item in data.get("transactions", [])
            ),
            recipients=tuple(
                Recipient.from_dict(item) for item in data.get("recipients", [])
            ),
        )


@dataclass(frozen=True, slots=True)
class TransferIntent:
    amount: Decimal
    recipient_id: str
    recipient_name: str

    def __post_init__(self) -> None:
        if self.amount <= 0:
            raise ValueError("transfer amount must be positive")
        if not self.recipient_id.strip():
            raise ValueError("recipient_id cannot be empty")

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> TransferIntent:
        return cls(
            amount=parse_money(data["amount"]),
            recipient_id=str(data["recipient_id"]),
            recipient_name=str(data.get("recipient_name", "Unknown recipient")),
        )


@dataclass(frozen=True, slots=True)
class FinancialContext:
    customer_id: str
    primary_account_id: str
    accounts: tuple[AccountSnapshot, ...]
    transfer_intent: TransferIntent | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.customer_id.strip():
            raise ValueError("customer_id cannot be empty")
        account_ids = {account.account_id for account in self.accounts}
        if not self.accounts:
            raise ValueError("financial context must contain an account")
        if self.primary_account_id not in account_ids:
            raise ValueError("primary_account_id must reference an account")
        if len(account_ids) != len(self.accounts):
            raise ValueError("account IDs must be unique")

    @property
    def primary_account(self) -> AccountSnapshot:
        return next(
            account
            for account in self.accounts
            if account.account_id == self.primary_account_id
        )

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> FinancialContext:
        transfer_data = data.get("transfer_intent")
        return cls(
            customer_id=str(data["customer_id"]),
            primary_account_id=str(data["primary_account_id"]),
            accounts=tuple(
                AccountSnapshot.from_dict(item) for item in data["accounts"]
            ),
            transfer_intent=(
                TransferIntent.from_dict(transfer_data)
                if transfer_data is not None
                else None
            ),
            metadata=dict(data.get("metadata", {})),
        )


class FindingKind(StrEnum):
    CLAIMED_TRANSACTION_NOT_FOUND = "claimed_transaction_not_found"
    NEW_RECIPIENT = "new_recipient"
    LARGE_TRANSFER = "large_transfer"
    INSUFFICIENT_FUNDS = "insufficient_funds"


@dataclass(frozen=True, slots=True)
class FinancialFinding:
    finding_id: str
    kind: FindingKind
    description: str
    risk_weight: int
    account_id: str
    source_signal_ids: tuple[str, ...] = ()
    attributes: dict[str, Any] = field(default_factory=dict)


_MONEY_TOLERANCE = Decimal("0.01")
_LARGE_TRANSFER_RATIO = Decimal("0.50")


class FinancialContextVerifier:
    """Compare caller claims and requested actions with account facts."""

    def verify(
        self,
        analysis: AnalysisResult,
        context: FinancialContext,
    ) -> tuple[FinancialFinding, ...]:
        findings: list[FinancialFinding] = []
        account = context.primary_account

        for signal in analysis.signals:
            if signal.kind == SignalKind.CLAIMED_TRANSACTION:
                finding = self._check_claimed_transaction(signal, account, len(findings))
                if finding is not None:
                    findings.append(finding)

        transfer_signals = tuple(
            signal
            for signal in analysis.signals
            if signal.kind == SignalKind.REQUESTED_TRANSFER
        )
        if transfer_signals:
            findings.extend(
                self._check_transfer(
                    transfer_signals,
                    context,
                    finding_offset=len(findings),
                )
            )

        return tuple(findings)

    def _check_claimed_transaction(
        self,
        signal: EvidenceSignal,
        account: AccountSnapshot,
        finding_offset: int,
    ) -> FinancialFinding | None:
        raw_amount = signal.attributes.get("amount")
        if raw_amount is None:
            return None
        amount = parse_money(raw_amount)
        has_match = any(
            abs(transaction.amount - amount) <= _MONEY_TOLERANCE
            and transaction.status.lower() in {"pending", "posted"}
            for transaction in account.transactions
        )
        if has_match:
            return None

        return FinancialFinding(
            finding_id=f"finding-{finding_offset + 1:04d}",
            kind=FindingKind.CLAIMED_TRANSACTION_NOT_FOUND,
            description=(
                f"Caller claimed a {self._format_money(amount)} transaction, but no "
                "matching pending or posted transaction exists."
            ),
            risk_weight=25,
            account_id=account.account_id,
            source_signal_ids=(signal.signal_id,),
            attributes={"claimed_amount": str(amount), "match_found": False},
        )

    def _check_transfer(
        self,
        transfer_signals: tuple[EvidenceSignal, ...],
        context: FinancialContext,
        finding_offset: int,
    ) -> list[FinancialFinding]:
        account = context.primary_account
        intent = context.transfer_intent
        requested_amount = self._requested_amount(transfer_signals)
        transfer_amount = intent.amount if intent is not None else requested_amount
        source_ids = tuple(signal.signal_id for signal in transfer_signals)
        findings: list[FinancialFinding] = []

        if intent is not None:
            known_recipient = next(
                (
                    recipient
                    for recipient in account.recipients
                    if recipient.recipient_id == intent.recipient_id
                ),
                None,
            )
            if known_recipient is None or known_recipient.previous_transfer_count == 0:
                findings.append(
                    FinancialFinding(
                        finding_id=f"finding-{finding_offset + len(findings) + 1:04d}",
                        kind=FindingKind.NEW_RECIPIENT,
                        description=(
                            f"The requested transfer recipient, {intent.recipient_name}, "
                            "has no prior transfer history."
                        ),
                        risk_weight=18,
                        account_id=account.account_id,
                        source_signal_ids=source_ids,
                        attributes={
                            "recipient_id": intent.recipient_id,
                            "recipient_name": intent.recipient_name,
                            "previous_transfer_count": 0,
                        },
                    )
                )

        if transfer_amount is None:
            return findings

        ratio = (
            transfer_amount / account.available_balance
            if account.available_balance > 0
            else Decimal("Infinity")
        )
        if ratio >= _LARGE_TRANSFER_RATIO:
            findings.append(
                FinancialFinding(
                    finding_id=f"finding-{finding_offset + len(findings) + 1:04d}",
                    kind=FindingKind.LARGE_TRANSFER,
                    description=(
                        f"The requested {self._format_money(transfer_amount)} transfer "
                        f"is {self._format_percent(ratio)} of available funds."
                    ),
                    risk_weight=20,
                    account_id=account.account_id,
                    source_signal_ids=source_ids,
                    attributes={
                        "transfer_amount": str(transfer_amount),
                        "available_balance": str(account.available_balance),
                        "balance_ratio": str(ratio),
                    },
                )
            )

        if transfer_amount > account.available_balance:
            findings.append(
                FinancialFinding(
                    finding_id=f"finding-{finding_offset + len(findings) + 1:04d}",
                    kind=FindingKind.INSUFFICIENT_FUNDS,
                    description=(
                        f"The requested {self._format_money(transfer_amount)} transfer "
                        "exceeds the available balance."
                    ),
                    risk_weight=12,
                    account_id=account.account_id,
                    source_signal_ids=source_ids,
                    attributes={
                        "transfer_amount": str(transfer_amount),
                        "available_balance": str(account.available_balance),
                    },
                )
            )

        return findings

    @staticmethod
    def _requested_amount(signals: tuple[EvidenceSignal, ...]) -> Decimal | None:
        for signal in signals:
            amount = signal.attributes.get("amount")
            if amount is not None:
                return parse_money(amount)
        return None

    @staticmethod
    def _format_money(amount: Decimal) -> str:
        return f"${amount:,.2f}"

    @staticmethod
    def _format_percent(ratio: Decimal) -> str:
        if not ratio.is_finite():
            return "more than 100%"
        return f"{ratio * 100:.0f}%"
