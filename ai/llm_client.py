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
        # 如果调用方没传，主动从环境变量读取 (修复回放模式下首调 AI 丢失代理的问题)
        if not proxy:
            proxy = os.getenv("AI_PROXY")
            
        _SHARED_SESSION = requests.Session()
        if proxy:
            _SHARED_SESSION.proxies = {"http": proxy, "https": proxy}
            print(f"  [Init] AI 会话已建立，使用代理: {proxy}")
            
    return _SHARED_SESSION

def _save_prompt_log(messages, response_text, model, error=None):
    """将 Prompt 和 响应持久化到本地供审计 (仅在 SAVE_PROMPTS=1 时触发)"""
    if os.getenv("SAVE_PROMPTS") != "1":
        return
    
    import hashlib
    log_dir = os.path.join("artifacts", "logs", "prompts")
    os.makedirs(log_dir, exist_ok=True)
    
    timestamp = time.strftime("%H%M%S")
    # 生成内容的短哈希防止文件名过长
    msg_hash = hashlib.md5(str(messages[-1]).encode()).hexdigest()[:6]
    status = "error" if error else "ok"
    filename = f"p_{timestamp}_{model.replace('/','_')}_{msg_hash}_{status}.json"
    
    dump_data = {
        "timestamp": datetime.now().isoformat() if 'datetime' in globals() else time.ctime(),
        "model": model,
        "messages": messages,
        "response": response_text,
        "error": error
    }
    
    try:
        with open(os.path.join(log_dir, filename), 'w', encoding='utf-8') as f:
            json.dump(dump_data, f, indent=2, ensure_ascii=False)
    except:
        pass

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
    """决策入口 (决策属于关键动作，使用 3 次重试 + 60s 超时)"""
    api_key, base_url, model, mode, proxy = _get_api_config()
    
    if mode == "auto" and api_key:
        return _decide_auto(messages, api_key, base_url, model, proxy, allow_interactive=allow_interactive)
    else:
        if not allow_interactive:
            return {"status": "unknown", "action": "wait", "value": "2000", "reason": "AI unavailable"}
        return _decide_interactive(messages)


def query_llm(messages: List[Dict[str, str]], json_mode: bool = False, proxy: str = None, logger=None, timeout: int = 60, max_retries: int = 3) -> str:
    """通用的 LLM 调用接口 (带日志反馈的手动重试版)"""
    global _SESSION_TOKEN_USAGE
    api_key, base_url, model, mode, _ = _get_api_config()
    
    if not api_key:
        return "Error: AI_API_KEY not set."

    log = logger if logger else print
    session = _get_shared_session(proxy)
    full_url = base_url.rstrip("/") + "/chat/completions"
    
    last_error = "Unknown error"
    for attempt in range(max_retries):
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

            if "thinking" in model.lower():
                 payload["reasoning_effort"] = "high"
            
            if json_mode:
                if "thinking" in model.lower() or "o1" in model.lower():
                    payload["response_format"] = {"type": "json_object"}

            log(f"  [LLM] 正在请求 API (模型: {model}, 尝试: {attempt + 1}/{max_retries}, 超时: {timeout}s)...", flush=True)
            
            # 在发送前先记录一次 (防止超时导致完全没记录)
            if attempt == 0:
                _save_prompt_log(messages, "PENDING...", model)

            response = session.post(full_url, headers=headers, json=payload, timeout=timeout)
            response.raise_for_status()
            
            log(f"  [LLM] 请求成功 (响应: {len(response.text)} bytes)", flush=True)
            
            # 请求成功，记录完整内容
            _save_prompt_log(messages, response.text, model)
            
            res_json = response.json()
            message = res_json["choices"][0]["message"]
            content = message.get("content", "")
            
            # [NEW] 提取推理思维链 (Reasoning / Thinking)
            # ... (保持原有的推理提取逻辑)
            reasoning = message.get("reasoning_content") or message.get("reasoning") or message.get("thinking")
            import re
            if not reasoning:
                thought_match = re.search(r'<thought>(.*?)</thought>', content, re.DOTALL | re.IGNORECASE)
                if thought_match:
                    reasoning = thought_match.group(1).strip()
                    content = re.sub(r'<thought>.*?</thought>', '', content, flags=re.DOTALL | re.IGNORECASE).strip()
                elif "```json" in content:
                    parts = content.split("```json")
                    pre_text = parts[0].strip()
                    if len(pre_text) > 10:
                        reasoning = pre_text
                        content = "```json" + parts[1]

            show_thoughts = int(os.environ.get("SHOW_THOUGHTS", "0"))
            if reasoning and show_thoughts != 0:
                print(f"\n💭 [AI 逻辑推演]\n{reasoning}\n" + "-"*30)

            if "usage" in res_json:
                usage = res_json["usage"]
                _SESSION_TOKEN_USAGE["prompt"] += usage.get("prompt_tokens", 0)
                _SESSION_TOKEN_USAGE["completion"] += usage.get("completion_tokens", 0)
                _SESSION_TOKEN_USAGE["total"] += usage.get("total_tokens", 0)
                _SESSION_TOKEN_USAGE["thoughts"] += usage.get("thoughts_token_count", 0) or usage.get("thoughts_tokens", 0)

            return content

        except Exception as e:
            last_error = str(e)
            if hasattr(e, 'response') and e.response is not None:
                last_error += f" (HTTP {e.response.status_code}: {e.response.text[:200]})"
            
            log(f"  [WARN] LLM 第 {attempt + 1} 次尝试异常: {last_error}", flush=True)
            
            # 记录错误现场
            _save_prompt_log(messages, "FAILED", model, error=last_error)
            
            # 如果是 429 (频率受限)，多等一会儿
            if "429" in last_error:
                log(f"  [Info] 触发频率限制，等待 5s 后重试...", flush=True)
                time.sleep(5)
            elif attempt < max_retries - 1:
                log(f"  [Info] 等待 2s 后进行下一次重试...", flush=True)
                time.sleep(2)
            else:
                log(f"  [Error] 已达到最大重试次数，放弃请求。", flush=True)

    return f"Error: {last_error}"

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
