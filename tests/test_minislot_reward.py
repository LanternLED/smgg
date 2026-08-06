import unittest

from cogs.minislot import apply_spin_reward


class MiniSlotRewardTests(unittest.TestCase):
    def test_apply_spin_reward_deducts_spin_cost_and_updates_exp(self):
        user_scores = {"chips": 100, "exp": 0, "booster": 0}

        bonus = apply_spin_reward(user_scores, 60, spin_cost=50, exp_rate=0.02)

        self.assertEqual(bonus, 0)
        self.assertEqual(user_scores["chips"], 110)
        self.assertEqual(user_scores["exp"], 1)


if __name__ == "__main__":
    unittest.main()
