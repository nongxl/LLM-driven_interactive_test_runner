import hashlib
import json

class StateMemory:
    def __init__(self):
        # 记录已访问的状态 ID
        self.visited_states = set()
        # 记录每个状态下已执行的动作 Map: state_id -> set(action_hash)
        self.state_actions = {}

    def get_state_id(self, snapshot):
        """生成状态唯一标识 (基于 ARIA 文本的哈希)"""
        aria_text = snapshot.get('aria_text', '')
        # 如果有 URL，可以结合 URL，但 ARIA 结构通常更可靠
        return hashlib.md5(aria_text.encode('utf-8')).hexdigest()

    def is_state_visited(self, state_id):
        """判断状态是否已访问"""
        return state_id in self.visited_states

    def mark_state(self, state_id):
        """标记状态为已访问"""
        self.visited_states.add(state_id)

    def is_action_visited(self, state_id, action_dict):
        """判断在特定状态下，某个动作是否已执行过"""
        if state_id not in self.state_actions:
            return False
        action_hash = self._hash_action(action_dict)
        return action_hash in self.state_actions[state_id]

    def mark_action(self, state_id, action_dict):
        """记录在特定状态下执行了某个动作"""
        if state_id not in self.state_actions:
            self.state_actions[state_id] = set()
        action_hash = self._hash_action(action_dict)
        self.state_actions[state_id].add(action_hash)

    def _hash_action(self, action_dict):
        """对动作字典进行哈希处理"""
        # 排除可能变化的随机值（如果有），确保相同的操作逻辑产生相同的哈希
        action_str = json.dumps(action_dict, sort_keys=True)
        return hashlib.md5(action_str.encode('utf-8')).hexdigest()
