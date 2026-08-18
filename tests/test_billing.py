from decimal import Decimal
import unittest

from voicely_billing import token_cost_microusd


class BillingTests(unittest.TestCase):
    def test_token_cost_uses_exact_decimal_rounding(self):
        self.assertEqual(token_cost_microusd(
            1, 1, Decimal("1.25"), Decimal("5.00"), Decimal("1.5")
        ), 9)

    def test_negative_token_counts_are_not_charged(self):
        self.assertEqual(token_cost_microusd(
            -100, -100, Decimal("1.25"), Decimal("5.00"), Decimal("1.5")
        ), 0)
