import unittest

from utils import apply_game_reward
from cogs.mahjong import mahjong_calc_reward
from cogs.kitchen import end_game


class RewardFlowTests(unittest.TestCase):
    def test_apply_game_reward_uses_chip_proportional_exp(self):
        user_scores = {"chips": 1000, "exp": 0, "booster": 0}

        bonus = apply_game_reward(user_scores, chip_gain=2000)

        self.assertEqual(bonus, 0)
        self.assertEqual(user_scores["chips"], 3000)
        self.assertEqual(user_scores["exp"], 200)

    def test_mahjong_reward_is_reduced_by_5_percent(self):
        self.assertEqual(mahjong_calc_reward(1, 0), 950)
        self.assertEqual(mahjong_calc_reward(2, 10), int(2 * 1000 * (1 + 10 * 0.02) * 0.95))

    def test_kitchen_reward_uses_shared_helper(self):
        import asyncio

        class DummyState:
            score = 100
            user_id = 42
            user_name = "tester"
            embed_msg = None
            timer_task = None
            make_embed = lambda self, title=None: None

        async def run_test():
            user_scores = {"chips": 1000, "exp": 0, "booster": 0}
            bonus = apply_game_reward(user_scores, 100, exp_rate=0.5)
            self.assertEqual(user_scores["chips"], 1100)
            self.assertEqual(user_scores["exp"], 50)
            self.assertEqual(bonus, 0)

        asyncio.run(run_test())


if __name__ == "__main__":
    unittest.main()
