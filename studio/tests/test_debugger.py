from __future__ import annotations

import unittest

from studio.debugger import ConditionDebugger


class ConditionDebuggerTests(unittest.TestCase):
    def test_explains_the_failing_leaf_and_then_unlocks(self) -> None:
        condition = {
            "op": "all",
            "conditions": [
                {"op": "eq", "symbol": "boss.hp", "value": 0},
                {"op": "eq", "symbol": "battle.id", "value": 7},
            ],
        }
        debugger = ConditionDebugger(["boss.hp", "battle.id"], condition)
        failed = debugger.tick({"boss.hp": 0, "battle.id": 6}, 0)
        self.assertFalse(failed.condition)
        self.assertTrue(any(line.passed is False and "battle.id" in line.text for line in failed.lines))
        passed = debugger.tick({"boss.hp": 0, "battle.id": 7}, 100)
        self.assertTrue(passed.condition)
        self.assertGreater(passed.instructions, 0)

    def test_hit_counter_state_is_visible(self) -> None:
        condition = {
            "op": "hit_count",
            "condition": {"op": "eq", "symbol": "hit", "value": 1},
            "count": 2,
        }
        debugger = ConditionDebugger(["hit"], condition)
        debugger.tick({"hit": 0}, 0)
        debugger.tick({"hit": 1}, 1)
        report = debugger.tick({"hit": 0}, 2)
        self.assertTrue(any("count=1" in line.text for line in report.lines))
        self.assertTrue(report.disassembly)


if __name__ == "__main__":
    unittest.main()

