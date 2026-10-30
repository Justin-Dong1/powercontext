"""Ticket listing baseline: optional status is not implemented yet."""


def list_tickets(tickets, status=None):
    return [dict(ticket) for ticket in tickets]
