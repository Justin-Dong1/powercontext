"""Utilities for listing tickets with optional exact status filtering."""


def list_tickets(tickets, status=None):
    """Return shallow copies of tickets, optionally filtered by exact status."""
    if status is None:
        return [dict(ticket) for ticket in tickets]

    return [dict(ticket) for ticket in tickets if ticket.get("status") == status]
