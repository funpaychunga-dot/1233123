"""Telegram Stars (XTR)."""
from __future__ import annotations

import json
import logging
from typing import Any, Optional

from services.payments.base import (
    Invoice, PaymentProvider, PaymentResult, PreCheckoutResult,
)

logger = logging.getLogger(__name__)

MAX_PAYLOAD_BYTES = 128


class StarsProvider(PaymentProvider):
    code = "stars"
    display_name = "Telegram Stars"
    currency = "XTR"

    async def create_invoice(
        self,
        *,
        user_id: int,
        amount: int,
        title: str,
        description: str,
        payload: dict[str, Any],
    ) -> Invoice:
        if amount <= 0:
            raise ValueError("Сумма должна быть > 0")
        payload = {**payload, "user_id": user_id}
        payload_str = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
        if len(payload_str.encode("utf-8")) > MAX_PAYLOAD_BYTES:
            raise ValueError(f"payload > {MAX_PAYLOAD_BYTES} байт")
        return Invoice(
            title=title,
            description=description,
            payload=payload_str,
            amount=amount,
            currency=self.currency,
            provider_token="",
        )

    async def validate_pre_checkout(
        self, *, payload: str, amount: int, currency: str,
    ) -> PreCheckoutResult:
        if currency != self.currency:
            return PreCheckoutResult(ok=False, error_message="Неверная валюта")
        if amount <= 0:
            return PreCheckoutResult(ok=False, error_message="Неверная сумма")
        return PreCheckoutResult(ok=True)

    async def parse_successful_payment(
        self,
        *,
        telegram_payment_charge_id: str,
        provider_payment_charge_id: Optional[str],
        payload: str,
        amount: int,
        currency: str,
    ) -> PaymentResult:
        try:
            data = json.loads(payload)
        except json.JSONDecodeError:
            data = {}
        return PaymentResult(
            user_id=int(data.get("user_id", 0)),
            amount=amount,
            currency=currency,
            provider=self.code,
            charge_id=telegram_payment_charge_id,
            payload=data,
            telegram_payment_charge_id=telegram_payment_charge_id,
        )
