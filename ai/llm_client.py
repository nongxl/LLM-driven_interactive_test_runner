import os
import json
import time
import sys
import requests
from typing import Dict, Any, List
from dotenv import load_dotenv

# ���� .env �����ļ�
load_dotenv()

# ==========================================
# 交互式测�?Agent 决策引擎 (真·自�?交互双模�?
# ==========================================

_SESSION_TOKEN_USAGE = 0

def _get_api_config():
    """从环境变量获�?AI 配置"""
    api_key = os.getenv("AI_API_KEY") or os.getenv("OPENAI_API_KEY") or os.getenv("DASHSCOPE_API_KEY")
    base_url = os.getenv("AI_BASE_URL", "https://api.openai.com/v1")
    model = os.getenv("AI_MODEL", "gpt-4o")
    mode = os.getenv("EXECUTION_MODE", "auto" if api_key else "interactive").lower()
    return api_key, base_url, model, mode

def decide_action(messages: list, allow_interactive: bool = True) -> Dict[str, Any]:
    """
    决策入口�?
    支持 'auto' (自动调用 LLM) �?'interactive' (手动终端输入) 两种模式�?
    """
    api_key, base_url, model, mode = _get_api_config()
    
    if mode == "auto" and api_key:
        return _decide_auto(messages, api_key, base_url, model)
    else:
        if not allow_interactive:
            # 静默模式下，如果无法自动决策，则返回默认“未�?等待”状�?
            return {"status": "unknown", "action": "wait", "value": "2000", "reason": "AI unavailable in silent mode"}
        return _decide_interactive(messages)


def query_llm(messages: List[Dict[str, str]], json_mode: bool = False) -> str:
    """通用�?LLM 调用接口，返回原始字符串内容"""
    global _SESSION_TOKEN_USAGE
    api_key, base_url, model, mode = _get_api_config()
    
    if not api_key:
        return "Error: AI_API_KEY not set. Cannot perform AI query."

    try:
        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json"
        }
        
        payload = {
            "model": model,
            "messages": messages,
            "temperature": 0.3
        }
        
        if json_mode:
            payload["response_format"] = {"type": "json_object"}
            # 强制要求 JSON 输出的提示增�?
            if messages and messages[0]["role"] == "system":
                # Create a mutable copy of messages if it's a tuple or immutable list
                if isinstance(messages, tuple):
                    messages = list(messages)
                if "JSON" not in messages[0]["content"]:
                     messages[0]["content"] += "\nReturn ONLY valid JSON format."

        response = requests.post(f"{base_url}/chat/completions", headers=headers, json=payload, timeout=60)
        response.raise_for_status()
        
        res_json = response.json()
        content = res_json["choices"][0]["message"]["content"]
        
        if "usage" in res_json:
            _SESSION_TOKEN_USAGE += res_json["usage"].get("total_tokens", 0)

        return content
    except Exception as e:
        return f"Error querying LLM: {str(e)}"

def _decide_auto(messages: List[Dict[str, str]], api_key: str, base_url: str, model: str) -> Dict[str, Any]:
    """自动模式：调用外�?LLM API 进行决策"""
    print(f"🤖 [自动模式] 正在请求 AI 决策 (Model: {model})...")
    
    content = query_llm(messages, json_mode=True)
    if content.startswith("Error"):
        print(f"�?[自动模式] 请求失败: {content}")
        print("🔁 降级为手动交互模�?..")
        return _decide_interactive(messages)

    try:
        # 解析决策
        decision = json.loads(content)
        print(f"�?AI 决策已获�? {json.dumps(decision, ensure_ascii=False)}")
        return decision
    except Exception as e:
        print(f"�?[自动模式] JSON 解析失败: {str(e)}")
        print("🔁 降级为手动交互模�?..")
        return _decide_interactive(messages)

def _decide_interactive(messages: list) -> Dict[str, Any]:
    """手动模式：打印上下文并等待终端输�?""
    global _SESSION_TOKEN_USAGE
    
    # 获取当前最新快照和目标
    last_aria = ""
    target_goal = ""
    for m in reversed(messages):
        if m.get("role") == "user":
            content = m.get("content", "")
            if "Target:" in content or "目标:" in content:
                 target_goal = content
            if "ARIA Tree:" in content or "ref=" in content:
                 last_aria = content
                 break

    print("\n" + "="*60)
    print("🤖 [手动核准模式] 请输入下一步操作指�?(仅限�?JSON 格式)")
    
    # [Data Audit]
    data_reminders = []
    if "admin" in target_goal.lower(): data_reminders.append("admin")
    if "密码" in target_goal: data_reminders.append("YAML指定密码")
    
    print(f"🎯 当前目标: {target_goal[:120]}...")
    if data_reminders:
        print(f"📌 [数据审计提醒]: \033[96m请严格使用指令提及的数据: {', '.join(data_reminders)}\033[0m")
    print("-" * 30)
    
    # [Sentinel] 提取并高亮显示页面告�?
    if "🔔" in last_aria:
         import re
         alert_match = re.search(r"🔔 \[System Alerts/Notifications\]: (.*?)\n", last_aria)
         if alert_match:
             print(f"🚨 [发现页面告警]: \033[93m{alert_match.group(1)}\033[0m")
             print("-" * 30)

    # 显示 ARIA Tree
    print(last_aria) 
    print("="*60)
    
    while True:
        try:
            user_input = input(">> 命令输入: ").strip()
            if not user_input: continue
            
            # [Feature] 快速退出指令支�?
            if user_input.lower() in ('exit', 'quit', 'q', ':q'):
                return {"action": "force_exit", "reason": "User requested exit"}

            # [Feature] "+" 快捷连接符支�?(自动注入 in_progress)
            is_in_progress = False
            if user_input.endswith("+"):
                is_in_progress = True
                user_input = user_input[:-1].strip()

            action_dict = json.loads(user_input)
            
            # 如果使用�?"+" �?JSON 中未显式指定状态，则注�?in_progress
            if is_in_progress and "task_status" not in action_dict:
                action_dict["task_status"] = "in_progress"

            print(f"�?指令已接�? {json.dumps(action_dict, ensure_ascii=False)}")
            return action_dict
        except json.JSONDecodeError:
            print("�?输入格式错误，请确保输出为纯 JSON (例如: {\"action\": \"click\", \"target\": \"e1\"})")
            print("💡 提示: 退出请输入 'exit'，多步连续操作可在命令末尾加 '+' (�? {\"action\":\"click\", \"target\":\"e1\"}+)")
        except EOFError:
            print("🛑 输入流中断�?)
            return {"action": "wait", "value": "2000"}

def get_current_token_usage() -> int:
    return _SESSION_TOKEN_USAGE
