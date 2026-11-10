"""Заглушка: криптовалюта — подключим позже."""
from __future__ import annotations

from typing import Any

from services.payments.base import (
    Invoice, PaymentProvider, PaymentResult, PreCheckoutResult,
)


class CryptoProvider(PaymentProvider):
    code = "crypto"
    display_name = "Криптовалюта (USDT/TON)"
    currency = "USDT"

    async def is_available(self) -> bool:
        return False

    async def create_invoice(self, **kwargs: Any) -> Invoice:
        raise NotImplementedError("Провайдер 'crypto' пока не подключён")

    async def validate_pre_checkout(self, **kwargs: Any) -> PreCheckoutResult:
        return PreCheckoutResult(ok=False, error_message="Провайдер недоступен")

    async def parse_successful_payment(self, **kwargs: Any) -> PaymentResult:
        raise NotImplementedError("Провайдер 'crypto' пока не подключён")
