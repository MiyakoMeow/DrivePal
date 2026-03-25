"""
测试数据生成器
使用comma2k19/D3S数据集作为模拟驾驶环境的数据源
"""

import random
import json
import os
from typing import List, Dict


class TestDataGenerator:
    """生成模拟驾驶场景的测试用例"""

    def __init__(self, config_dir: str = "config"):
        self.config_dir = config_dir
        self._scenarios = None
        self._driver_states = None

    @property
    def SCENARIOS(self) -> List[Dict]:
        if self._scenarios is None:
            config_path = os.path.join(self.config_dir, "scenarios.json")
            if os.path.exists(config_path):
                with open(config_path, "r", encoding="utf-8") as f:
                    self._scenarios = json.load(f)
            else:
                self._scenarios = []
        return self._scenarios

    @property
    def DRIVER_STATES(self) -> List[Dict]:
        if self._driver_states is None:
            config_path = os.path.join(self.config_dir, "driver_states.json")
            if os.path.exists(config_path):
                with open(config_path, "r", encoding="utf-8") as f:
                    self._driver_states = json.load(f)
            else:
                self._driver_states = []
        return self._driver_states

    def generate_test_cases(self, count: int = 20) -> List[Dict]:
        """生成测试用例"""
        test_cases = []
        for _ in range(count):
            if not self.SCENARIOS:
                scenario = {"type": "unknown", "templates": ["无场景模板"]}
            else:
                scenario = random.choice(self.SCENARIOS)

            templates = scenario.get("templates", [])
            template = random.choice(templates) if templates else "无模板内容"

            driver_state = (
                random.choice(self.DRIVER_STATES)
                if self.DRIVER_STATES
                else {"state": "unknown"}
            )

            test_cases.append(
                {
                    "input": template,
                    "type": scenario["type"],
                    "driver_state": driver_state,
                    "time_context": self._random_time_context(),
                }
            )
        return test_cases

    def _random_time_context(self) -> Dict:
        hour = random.randint(8, 20)
        return {
            "hour": hour,
            "traffic": random.choice(["smooth", "congested", "moderate"]),
            "location": random.choice(["home", "office", "driving"]),
        }
