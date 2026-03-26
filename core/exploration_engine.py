import re
from typing import List, Dict, Any, Optional
from core.strategy import StrategyManager, ExplorationStrategy

class ExplorationEngine:
    def __init__(self, strategy_type=ExplorationStrategy.COVERAGE_FIRST):
        self.strategy_manager = StrategyManager(strategy_type)

    def get_actions_from_snapshot(self, snapshot: Dict[str, Any]) -> List[Dict[str, Any]]:
        """
        从 ARIA 文本中解析所有可交互元素。
        格式通常为 [ref] Role "Name"
        """
        aria_text = snapshot.get('aria_text', '')
        actions = []
        
        # 正则匹配适配 agent-browser 格式: - role "Name" [ref=eID] (可能伴随 focusable, clickable 等)
        pattern = r'- (button|link|textbox|checkbox|combobox|menuitem|tab|generic)\s+"([^"]*)"\s+\[ref=(e\d+)[^\]]*\]'
        matches = re.finditer(pattern, aria_text)
        
        for match in matches:
            role = match.group(1)
            name = match.group(2)
            ref = match.group(3)
            
            # 根据角色决定动作类型
            action_type = "click"
            if role in ["textbox", "combobox"]:
                action_type = "type"
                
            actions.append({
                "action": action_type,
                "target": ref, # 必须显式添加 target 供 action_executor 使用
                "ref": ref,
                "role": role,
                "name": name,
                "value": "exploratory_input" if action_type == "type" else None
            })

            
        return actions

    async def assess_page_health(self, snapshot: Dict[str, Any]) -> Dict[str, Any]:
        """
        利用 LLM 对当前页面状态进行业务层面的“健康检查”。
        """
        from ai.llm_client import decide_action
        from ai.prompt_builder import init_step_messages
        
        aria_text = snapshot.get('aria_text', '')
        url = snapshot.get('url', '')
        
        prompt = f"你是一个高级测试专家。请评估当前页面状态（URL: {url}）。\n" \
                 f"页面内容 (ARIA Tree):\n{aria_text}\n\n" \
                 f"请判断：\n" \
                 f"1. 页面是否加载成功？\n" \
                 f"2. 是否存在业务错误提示（如 404, 500, 权限不足, 登录失败）？\n" \
                 f"3. 页面是否处于期望的业务流程中？\n\n" \
                 f"返回 JSON 格式：\n" \
                 f"{{\"status\": \"healthy|error|unknown\", \"reason\": \"原因描述\", \"score\": 0.0-1.0}}"
        
        messages = [{"role": "user", "content": prompt}]
        try:
            # [V2] 使用静默模式，防止 API 缺失时阻塞
            assessment = decide_action(messages, allow_interactive=False)
            return assessment

        except Exception as e:
            return {"status": "unknown", "reason": f"AI 评估异常: {str(e)}", "score": 0.5}

    def decide_next_step(self, snapshot: Dict[str, Any], state_memory) -> Optional[Dict[str, Any]]:

        """决定下一步动作"""
        state_id = state_memory.get_state_id(snapshot)
        all_actions = self.get_actions_from_snapshot(snapshot)
        
        if not all_actions:
            return None
            
        # 记录该状态被发现
        state_memory.mark_state(state_id)
        
        # 调用策略选择动作
        selected_action = self.strategy_manager.get_action(state_id, all_actions, state_memory)
        
        if selected_action:
            # 标记该动作已在该状态下执行
            state_memory.mark_action(state_id, selected_action)
            
        return selected_action
