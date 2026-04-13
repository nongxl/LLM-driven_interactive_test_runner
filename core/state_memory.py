import hashlib
import json
import time
import re

class StateMemory:
    def __init__(self, max_history=100):
        # 记录已访问的状态 ID (用于策略引导)
        self.visited_states = set()
        # 记录每个状态下已执行的动作 Map: state_id -> set(action_hash)
        self.state_actions = {}
        
        # [V4.0 新义] 核心记忆存储
        self.history = []               # 完整轨迹记录
        self.nav_path = []              # URL 访问序列
        self.max_history = max_history  # 用户定义的历史上限 (100+)

    def get_state_id(self, snapshot):
        """生成状态唯一标识 (基于 ARIA 文本的哈希)"""
        aria_text = snapshot.get('aria_text', '')
        # 如果有 URL，可以结合 URL，但 ARIA 结构通常更可靠
        return hashlib.md5(aria_text.encode('utf-8')).hexdigest()

    def record_step(self, action_dict, snapshot):
        """记录一步完整的操作序列"""
        url = snapshot.get('url', 'unknown')
        if not self.nav_path or self.nav_path[-1] != url:
            self.nav_path.append(url)
            
        step_info = {
            "timestamp": time.strftime("%H:%M:%S"),
            "action": action_dict,
            "url": url,
            "snapshot_summary": self._extract_summary(snapshot)
        }
        self.history.append(step_info)
        
        # 维持物理上限
        if len(self.history) > 1000:
            self.history.pop(0)

    def get_history_summary(self, max_detailed=10):
        """
        生成分层记忆摘要供 Prompt 使用
        - 近期 (N-max_detailed 到 N): 详细
        - 远期 (0 到 N-max_detailed): 极简压缩
        """
        if not self.history:
            return "无历史记录"
            
        total_steps = len(self.history)
        summary_lines = []
        
        # 1. 远期记忆 (Condensed)
        if total_steps > max_detailed:
            condensed_count = total_steps - max_detailed
            summary_lines.append(f"... (前 {condensed_count} 步操作已略，主要是系统导航与表单填入) ...")
            
            # 提取里程碑 (每 10 步取一个代表)
            for i in range(0, condensed_count, 10):
                step = self.history[i]
                summary_lines.append(f"  - [Step {i+1}] {step['action'].get('action')} @ {step['url']}")

        # 2. 近期记忆 (Detailed)
        detailed_start = max(0, total_steps - max_detailed)
        for i in range(detailed_start, total_steps):
            step = self.history[i]
            action = step['action']
            desc = f"- [{step['timestamp']}] {action.get('action', 'unknown')} "
            if action.get('name'):
                desc += f"\"{action.get('name')}\" "
            elif action.get('target'):
                desc += f"({action.get('target')}) "
            
            if action.get('value'):
                desc += f"-> {action.get('value')} "
            
            summary_lines.append(desc)
            
        return "\n".join(summary_lines)

    def _extract_summary(self, snapshot):
        """从快照提取简单的页面识别特征"""
        # 尝试寻找 H1 或页面标题样式的文字
        aria = snapshot.get('aria_text', '')
        match = re.search(r'heading "([^"]+)"', aria)
        if match:
            return match.group(1)
        return "未知页面"

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
