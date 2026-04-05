import unittest
import os
import json
from utils.cost_tracker import CostTracker, BudgetExceededError

class TestCostTracker(unittest.TestCase):
    def setUp(self):
        self.ledger_path = "test_ledger.json"
        
        if os.path.exists(self.ledger_path):
            os.remove(self.ledger_path)
            
        # Reset singleton instance
        CostTracker._instance = None
        self.tracker = CostTracker(limit_usd=1.0, ledger_path=self.ledger_path)

    def tearDown(self):
        if os.path.exists(self.ledger_path):
            os.remove(self.ledger_path)
        CostTracker._instance = None

    def test_calculate_cost(self):
        # Sonnet test: 1 million input = $3.0, 1 million output = $15.0
        cost = self.tracker.calculate_cost("claude-3-5-sonnet-20241022", 1_000_000, 1_000_000)
        self.assertAlmostEqual(cost, 18.0)
        
        # Haiku test: 1 million input = $1.0, 1 million output = $5.0
        cost2 = self.tracker.calculate_cost("claude-3-5-haiku-20241022", 500_000, 200_000)
        self.assertAlmostEqual(cost2, 1.5)

    def test_record_and_persist(self):
        # Haiku call 
        # cost = (1000/1M * 1) + (500/1M * 5) = 0.001 + 0.0025 = 0.0035
        self.tracker.record_call_cost("claude-3-5-haiku-20241022", 1000, 500, "generation")
        
        with open(self.ledger_path, 'r') as f:
            data = json.load(f)
        
        self.assertAlmostEqual(data["total_spend_usd"], 0.0035)
        self.assertEqual(data["breakdown_by_category"]["generation"]["tokens"], 1500)
        
    def test_budget_exceeded(self):
        # Record a massive cost to trigger boundary
        self.tracker.record_call_cost("claude-3-5-sonnet-20241022", 5_000_000, 0, "huge_call") # 5M in = $15.0 => over budget
        
        with self.assertRaises(BudgetExceededError):
            self.tracker.check_budget()

if __name__ == "__main__":
    unittest.main()
