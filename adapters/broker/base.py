"""Broker-agnostic executor interface. Real brokers (Upstox, ...) implement this in a later phase."""
from abc import ABC, abstractmethod

from core.models import Order


class Executor(ABC):
    live = False

    @abstractmethod
    def submit(self, order: Order) -> Order:
        """Validate and queue an order as PENDING (nothing executes yet)."""

    @abstractmethod
    def approve(self, order_id: int) -> Order:
        """Execute a PENDING order after explicit human approval."""

    @abstractmethod
    def reject(self, order_id: int, reason: str = "") -> Order: ...

    @abstractmethod
    def positions(self) -> list: ...
