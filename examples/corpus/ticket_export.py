"""Nightly job that copies closed tickets into the reporting warehouse."""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass


@dataclass
class Ticket:
    id: str
    product: str
    priority: str
    opened: dt.datetime
    closed: dt.datetime | None

    @property
    def resolution_hours(self) -> float | None:
        if self.closed is None:
            return None
        return (self.closed - self.opened).total_seconds() / 3600


def first_response_target(priority: str) -> dt.timedelta:
    """Targets from the onboarding handbook, in calendar time."""
    targets = {"P1": dt.timedelta(hours=4), "P2": dt.timedelta(days=1), "P3": dt.timedelta(days=3)}
    return targets[priority]


def breached(ticket: Ticket, first_response: dt.datetime) -> bool:
    return first_response - ticket.opened > first_response_target(ticket.priority)


def export(tickets: list[Ticket]) -> list[dict]:
    rows = []
    for ticket in tickets:
        if ticket.closed is None:
            continue
        rows.append(
            {
                "id": ticket.id,
                "product": ticket.product,
                "priority": ticket.priority,
                "resolution_hours": round(ticket.resolution_hours or 0, 1),
            }
        )
    return rows
