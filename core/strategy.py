from enum import Enum
import random

class ExplorationStrategy(Enum):
    RANDOM = "random"
    COVERAGE_FIRST = "coverage_first"
    DFS = "dfs"
    BFS = "bfs"

class BaseStrategy:
    def select_action(self, state_id, actions, state_memory):
        raise NotImplementedError

class CoverageFirstStrategy(BaseStrategy):
    """
    优先级：从未在该状态执行过的动作 > 从未在全局执行过的动作 (近似) > 随机动作
    """
    def select_action(self, state_id, actions, state_memory):
        if not actions:
            return None
        
        unvisited = [a for a in actions if not state_memory.is_action_visited(state_id, a)]
        
        if unvisited:
            # 在未访问的动作中随机选一个，保持一定的随机性以发现不同路径
            return random.choice(unvisited)
        
        # 如果所有动作都在该状态下执行过，则随机选一个（或考虑回退/停止）
        return random.choice(actions)

class DFSStrategy(BaseStrategy):
    """深度优先 (在该状态下优先探索分支)"""
    def select_action(self, state_id, actions, state_memory):
        # 简单实现：在这个上下文，DFS 类似于 CoverageFirst
        return CoverageFirstStrategy().select_action(state_id, actions, state_memory)

class BFSStrategy(BaseStrategy):
    """广度优先 (优先回到未完全探索的老状态)"""
    def select_action(self, state_id, actions, state_memory):
        # 简单实现：目前简单随机，真正的 BFS 需要 Runner 层面的队列控制
        return random.choice(actions) if actions else None

class StrategyManager:
    def __init__(self, strategy_type=ExplorationStrategy.COVERAGE_FIRST):
        self.strategy_type = strategy_type
        self.strategies = {
            ExplorationStrategy.COVERAGE_FIRST: CoverageFirstStrategy(),
            ExplorationStrategy.DFS: DFSStrategy(),
            ExplorationStrategy.BFS: BFSStrategy(),
            ExplorationStrategy.RANDOM: BaseStrategy() # 可以直接在 runner 实现随机
        }

    def get_action(self, state_id, actions, state_memory):
        strategy = self.strategies.get(self.strategy_type, self.strategies[ExplorationStrategy.COVERAGE_FIRST])
        return strategy.select_action(state_id, actions, state_memory)
