import unittest
from tickets import list_tickets


class Compatibility(unittest.TestCase):
    def test_default_preserves_order_and_fields(self):
        rows = [
            {"id": 2, "status": "open", "title": "two"},
            {"id": 1, "status": "closed"},
        ]
        self.assertEqual(list_tickets(rows), rows)

    def test_returns_copies(self):
        row = {"id": 1, "status": "open"}
        out = list_tickets([row])
        out[0]["id"] = 9
        self.assertEqual(row["id"], 1)

    def test_empty(self):
        self.assertEqual(list_tickets([]), [])
