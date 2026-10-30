# Ticket status filtering

S-1: list_tickets(tickets, status=None) returns all tickets in input order.
S-2: A supplied status returns only tickets with exactly that status. Unknown status returns an empty list.
S-3: Return shallow copies; never mutate caller tickets. Retain ids and all fields.
S-4: Empty tickets returns an empty list. Preserve the function signature.
