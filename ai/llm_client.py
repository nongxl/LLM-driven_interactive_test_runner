import os
import json
import time
import sys
import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
from typing import Dict, Any, List
from dotenv import load_dotenv

# 加载 .env 配置文件
load_dotenv()

# ==========================================
# 交互式测试 Agent 决策引擎 (工业级长连接版)
# ==========================================

_SESSION_TOKEN_USAGE = {
    "prompt": 0,
    "completion": 0,
    "thoughts": 0,
    "total": 0
}
_SHARED_SESSION = None

def _get_shared_session(proxy=None):
    """获取单例 Session，支持连接池复用"""
    global _SHARED_SESSION
    if _SHARED_SESSION is None:
        _SHARED_SESSION = requests.Session()
        
        # 配置重试逻辑
        retry_strategy = Retry(
            total=3,
            backoff_factor=1,
            status_forcelist=[429, 500, 502, 503, 504],
        )
        adapter = HTTPAdapter(max_retries=retry_strategy)
        _SHARED_SESSION.mount("https://", adapter)
        _SHARED_SESSION.mount("http://", adapter)
        
        if proxy:
            _SHARED_SESSION.proxies = {"http": proxy, "https": proxy}
            
    return _SHARED_SESSION

def _get_api_config():
    """从环境变量或 .env 获取 AI 配置"""
    api_key = os.getenv("GOOGLE_API_KEY") or os.getenv("AI_API_KEY") or os.getenv("OPENAI_API_KEY") or os.getenv("DASHSCOPE_API_KEY")
    
    # 默认 Base URL
    default_base_url = "https://api.openai.com/v1"
    if os.getenv("GOOGLE_API_KEY") and not os.getenv("AI_BASE_URL"):
        default_base_url = "https://generativelanguage.googleapis.com/v1beta/openai/"
        
    base_url = os.getenv("AI_BASE_URL", default_base_url)
    model = os.getenv("AI_MODEL", "gemini-1.5-pro") # 升级默认模型至支持长期思考的版本
    mode = os.getenv("EXECUTION_MODE", "auto" if api_key else "interactive").lower()
    proxy = os.getenv("AI_PROXY")
    
    return api_key, base_url, model, mode, proxy

def decide_action(messages: list, allow_interactive: bool = True) -> Dict[str, Any]:
    """决策入口"""
    api_key, base_url, model, mode, proxy = _get_api_config()
    
    if mode == "auto" and api_key:
        return _decide_auto(messages, api_key, base_url, model, proxy, allow_interactive=allow_interactive)
    else:
        if not allow_interactive:
            return {"status": "unknown", "action": "wait", "value": "2000", "reason": "AI unavailable"}
        return _decide_interactive(messages)


def query_llm(messages: List[Dict[str, str]], json_mode: bool = False, proxy: str = None) -> str:
    """通用的 LLM 调用接口 (Session 复用版)"""
    global _SESSION_TOKEN_USAGE
    api_key, base_url, model, mode, _ = _get_api_config()
    
    if not api_key:
        return "Error: AI_API_KEY not set."

    session = _get_shared_session(proxy)
    
    try:
        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json"
        }
        
        payload = {
            "model": model,
            "messages": messages,
            "temperature": 0
        }

        # [Feature] 思考型支持
        # 仅针对明确支持高强度推理的模型开启参数，防止 lite 模型报错或失效
        if "thinking" in model.lower():
             payload["reasoning_effort"] = "high"
        
        # [v3.5] 兼容性改进：如果模型不支持原生的 reasoning_content，则关闭 json_mode
        # 强制 AI 在正文中先写思考再写 JSON，代码后续进行手动切割
        if json_mode:
            if "thinking" in model.lower() or "o1" in model.lower():
                payload["response_format"] = {"type": "json_object"}
            else:
                # Lite 或 Pro 模型不使用 JSON Mode，改为在 Prompt 中强制要求
                pass 

        full_url = base_url.rstrip("/") + "/chat/completions"
        
        response = session.post(full_url, headers=headers, json=payload, timeout=60)
        response.raise_for_status()
        
        res_json = response.json()
        message = res_json["choices"][0]["message"]
        content = message.get("content", "")
        
        # [NEW] 提取推理思维链 (Reasoning / Thinking)
        # 1. 优先获取模型原生返回的推理字段
        reasoning = message.get("reasoning_content") or message.get("reasoning") or message.get("thinking")
        
        # 2. 如果没有原生字段，尝试从正文中正则表达式提取 (处理 Pro/Lite 模型的内置思考)
        import re
        if not reasoning:
            # 尝试提取 <thought>...</thought> 标签内的内容
            thought_match = re.search(r'<thought>(.*?)</thought>', content, re.DOTALL | re.IGNORECASE)
            if thought_match:
                reasoning = thought_match.group(1).strip()
                # 从 content 中剔除已提取的思考内容，防止 JSON 解析报错
                content = re.sub(r'<thought>.*?</thought>', '', content, flags=re.DOTALL | re.IGNORECASE).strip()
            elif "```json" in content:
                # 尝试提取 ```json 块之前的描述文字作为推理过程
                parts = content.split("```json")
                pre_text = parts[0].strip()
                if len(pre_text) > 10: # 只有足够长的文字才视为推理
                    reasoning = pre_text
                    # 仅保留 JSON 块供后续解析
                    content = "```json" + parts[1]

        # 实时输出推理过程 (如果环境变量开启且存在推理内容)
        # [v3.6] 默认关闭 (0)，保护 Token 成本且控制台精简
        show_thoughts = int(os.environ.get("SHOW_THOUGHTS", "0"))
        if reasoning and show_thoughts != 0:
            print(f"\n💭 [AI 逻辑推演]\n{reasoning}\n" + "-"*30)

        if "usage" in res_json:
            usage = res_json["usage"]
            _SESSION_TOKEN_USAGE["prompt"] += usage.get("prompt_tokens", 0)
            _SESSION_TOKEN_USAGE["completion"] += usage.get("completion_tokens", 0)
            _SESSION_TOKEN_USAGE["total"] += usage.get("total_tokens", 0)
            # 兼容处理 Gemini 3 思考 Token (支持多种可能的透传 ID)
            _SESSION_TOKEN_USAGE["thoughts"] += usage.get("thoughts_token_count", 0) or usage.get("thoughts_tokens", 0)

        return content
    except Exception as e:
        error_msg = str(e)
        if hasattr(e, 'response') and e.response is not None:
            error_msg += f" (Detail: {e.response.text[:200]})"
        return f"Error: {error_msg}"

def _decide_auto(messages: List[Dict[str, str]], api_key: str, base_url: str, model: str, proxy: str = None, allow_interactive: bool = True) -> Dict[str, Any]:
    """自动模式"""
    show_thoughts = int(os.environ.get("SHOW_THOUGHTS", "0"))
    if show_thoughts != 0:
        print(f"🤖 [自动/思考模式] 正在请求推理决策 (Model: {model})...")
    
    content = query_llm(messages, json_mode=True, proxy=proxy)
    if content.startswith("Error"):
        print(f"❌ 请求失败: {content}")
        if allow_interactive:
            return _decide_interactive(messages)
        else:
            return {"status": "unknown", "action": "wait", "value": "2000", "reason": f"AI Error: {content}"}

    try:
        # 清理 Markdown 块
        if "```json" in content: content = content.split("```json")[1].split("```")[0].strip()
        elif "```" in content: content = content.split("```")[1].split("```")[0].strip()

        decision = json.loads(content)
        print(f"✅ 推理决策已获得: {json.dumps(decision, ensure_ascii=False)}")
        return decision
    except Exception as e:
        print(f"❌ JSON 解析失败: {str(e)}")
        if allow_interactive:
            return _decide_interactive(messages)
        else:
            return {"status": "unknown", "action": "wait", "value": "2000", "reason": f"JSON Parse Error: {str(e)}"}

def _decide_interactive(messages: list) -> Dict[str, Any]:
    """手动模式"""
    global _SESSION_TOKEN_USAGE
    
    last_aria = ""
    target_goal = ""
    for m in reversed(messages):
        if m.get("role") == "user":
            content = m.get("content", "")
            if "Target:" in content or "目标:" in content: target_goal = content
            if "ARIA Tree:" in content or "ref=" in content:
                 last_aria = content
                 break

    print("\n" + "="*60)
    print("🤖 [手动核准模式 - 网络故障自愈中] 请输入操作指令")
    print(f"🎯 当前目标: {target_goal[:120]}...")
    print("-" * 30)
    print(last_aria) 
    print("="*60)
    
    while True:
        try:
            user_input = input(">> 命令输入: ").strip()
            if not user_input: continue
            if user_input.lower() in ('exit', 'quit', 'q', ':q'):
                return {"action": "force_exit", "reason": "User requested exit"}

            is_in_progress = False
            if user_input.endswith("+"):
                is_in_progress = True
                user_input = user_input[:-1].strip()

            action_dict = json.loads(user_input)
            if is_in_progress and "task_status" not in action_dict:
                action_dict["task_status"] = "in_progress"

            print(f"✅ 指令已接收: {json.dumps(action_dict, ensure_ascii=False)}")
            return action_dict
        except json.JSONDecodeError:
            print("❌ 格式错误，请确保输出为纯 JSON")
        except EOFError:
            return {"action": "wait", "value": "2000"}

def get_current_token_usage() -> Dict[str, int]:
    return _SESSION_TOKEN_USAGE
