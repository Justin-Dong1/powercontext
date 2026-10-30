import unittest
from tickets import list_tickets


class StatusFilter(unittest.TestCase):
    def setUp(self):
        self.tickets = [
            {"id": 1, "status": "open"},
            {"id": 2, "status": "closed"},
            {"id": 3, "status": "open"},
        ]

    def test_open(self):
        self.assertEqual([x["id"] for x in list_tickets(self.tickets, "open")], [1, 3])

    def test_closed(self):
        self.assertEqual([x["id"] for x in list_tickets(self.tickets, "closed")], [2])

    def test_unknown(self):
        self.assertEqual(list_tickets(self.tickets, "unknown"), [])
