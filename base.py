"""Абстракция платёжного провайдера."""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Optional


@dataclass
class Invoice:
    title: str
    description: str
    payload: str       # сериализованная строка (для Stars — JSON)
    amount: int        # в минимальных единицах провайдера
    currency: str
    provider_token: str = ""  # для Stars — пусто


@dataclass
class PreCheckoutResult:
    ok: bool
    error_message: str = ""


@dataclass
class PaymentResult:
    user_id: int
    amount: int
    currency: str
    provider: str
    charge_id: str
    payload: dict[str, Any] = field(default_factory=dict)
    telegram_payment_charge_id: Optional[str] = None


class PaymentProvider(ABC):
    code: str = ""
    display_name: str = ""
    currency: str = ""

    async def is_available(self) -> bool:
        return True

    @abstractmethod
    async def create_invoice(
        self,
        *,
        user_id: int,
        amount: int,
        title: str,
        description: str,
        payload: dict[str, Any],
    ) -> Invoice: ...

    @abstractmethod
    async def validate_pre_checkout(
        self, *, payload: str, amount: int, currency: str,
    ) -> PreCheckoutResult: ...

    @abstractmethod
    async def parse_successful_payment(
        self,
        *,
        telegram_payment_charge_id: str,
        provider_payment_charge_id: Optional[str],
        payload: str,
        amount: int,
        currency: str,
    ) -> PaymentResult: ...
