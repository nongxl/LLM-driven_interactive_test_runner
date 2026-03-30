import os
import json
import time
import sys
import requests
from typing import Dict, Any, List
from dotenv import load_dotenv

# 加载 .env 配置文件
load_dotenv()

# ==========================================
# 浜や簰寮忔祴璇?Agent 鍐崇瓥寮曟搸 (鐪熉疯嚜鍔?浜や簰鍙屾ā鐗?
# ==========================================

_SESSION_TOKEN_USAGE = 0

def _get_api_config():
    """浠庣幆澧冨彉閲忚幏鍙?AI 閰嶇疆"""
    api_key = os.getenv("AI_API_KEY") or os.getenv("OPENAI_API_KEY") or os.getenv("DASHSCOPE_API_KEY")
    base_url = os.getenv("AI_BASE_URL", "https://api.openai.com/v1")
    model = os.getenv("AI_MODEL", "gpt-4o")
    mode = os.getenv("EXECUTION_MODE", "auto" if api_key else "interactive").lower()
    return api_key, base_url, model, mode

def decide_action(messages: list, allow_interactive: bool = True) -> Dict[str, Any]:
    """
    鍐崇瓥鍏ュ彛锛?
    鏀寔 'auto' (鑷姩璋冪敤 LLM) 鍜?'interactive' (鎵嬪姩缁堢杈撳叆) 涓ょ妯″紡銆?
    """
    api_key, base_url, model, mode = _get_api_config()
    
    if mode == "auto" and api_key:
        return _decide_auto(messages, api_key, base_url, model)
    else:
        if not allow_interactive:
            # 闈欓粯妯″紡涓嬶紝濡傛灉鏃犳硶鑷姩鍐崇瓥锛屽垯杩斿洖榛樿鈥滄湭鐭?绛夊緟鈥濈姸鎬?
            return {"status": "unknown", "action": "wait", "value": "2000", "reason": "AI unavailable in silent mode"}
        return _decide_interactive(messages)


def query_llm(messages: List[Dict[str, str]], json_mode: bool = False) -> str:
    """閫氱敤鐨?LLM 璋冪敤鎺ュ彛锛岃繑鍥炲師濮嬪瓧绗︿覆鍐呭"""
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
            # 寮哄埗瑕佹眰 JSON 杈撳嚭鐨勬彁绀哄寮?
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
    """鑷姩妯″紡锛氳皟鐢ㄥ閮?LLM API 杩涜鍐崇瓥"""
    print(f"馃 [鑷姩妯″紡] 姝ｅ湪璇锋眰 AI 鍐崇瓥 (Model: {model})...")
    
    content = query_llm(messages, json_mode=True)
    if content.startswith("Error"):
        print(f"鉂?[鑷姩妯″紡] 璇锋眰澶辫触: {content}")
        print("馃攣 闄嶇骇涓烘墜鍔ㄤ氦浜掓ā寮?..")
        return _decide_interactive(messages)

    try:
        # 瑙ｆ瀽鍐崇瓥
        decision = json.loads(content)
        print(f"鉁?AI 鍐崇瓥宸茶幏寰? {json.dumps(decision, ensure_ascii=False)}")
        return decision
    except Exception as e:
        print(f"鉂?[鑷姩妯″紡] JSON 瑙ｆ瀽澶辫触: {str(e)}")
        print("馃攣 闄嶇骇涓烘墜鍔ㄤ氦浜掓ā寮?..")
        return _decide_interactive(messages)

def _decide_interactive(messages: list) -> Dict[str, Any]:
    """鎵嬪姩妯″紡锛氭墦鍗颁笂涓嬫枃骞剁瓑寰呯粓绔緭鍏?""
    global _SESSION_TOKEN_USAGE
    
    # 鑾峰彇褰撳墠鏈€鏂板揩鐓у拰鐩爣
    last_aria = ""
    target_goal = ""
    for m in reversed(messages):
        if m.get("role") == "user":
            content = m.get("content", "")
            if "Target:" in content or "鐩爣:" in content:
                 target_goal = content
            if "ARIA Tree:" in content or "ref=" in content:
                 last_aria = content
                 break

    print("\n" + "="*60)
    print("馃 [鎵嬪姩鏍稿噯妯″紡] 璇疯緭鍏ヤ笅涓€姝ユ搷浣滄寚浠?(浠呴檺绾?JSON 鏍煎紡)")
    
    # [Data Audit]
    data_reminders = []
    if "admin" in target_goal.lower(): data_reminders.append("admin")
    if "瀵嗙爜" in target_goal: data_reminders.append("YAML鎸囧畾瀵嗙爜")
    
    print(f"馃幆 褰撳墠鐩爣: {target_goal[:120]}...")
    if data_reminders:
        print(f"馃搶 [鏁版嵁瀹¤鎻愰啋]: \033[96m璇蜂弗鏍间娇鐢ㄦ寚浠ゆ彁鍙婄殑鏁版嵁: {', '.join(data_reminders)}\033[0m")
    print("-" * 30)
    
    # [Sentinel] 鎻愬彇骞堕珮浜樉绀洪〉闈㈠憡璀?
    if "馃敂" in last_aria:
         import re
         alert_match = re.search(r"馃敂 \[System Alerts/Notifications\]: (.*?)\n", last_aria)
         if alert_match:
             print(f"馃毃 [鍙戠幇椤甸潰鍛婅]: \033[93m{alert_match.group(1)}\033[0m")
             print("-" * 30)

    # 鏄剧ず ARIA Tree
    print(last_aria) 
    print("="*60)
    
    while True:
        try:
            user_input = input(">> 鍛戒护杈撳叆: ").strip()
            if not user_input: continue
            
            # [Feature] 蹇€熼€€鍑烘寚浠ゆ敮鎸?
            if user_input.lower() in ('exit', 'quit', 'q', ':q'):
                return {"action": "force_exit", "reason": "User requested exit"}

            # [Feature] "+" 蹇嵎杩炴帴绗︽敮鎸?(鑷姩娉ㄥ叆 in_progress)
            is_in_progress = False
            if user_input.endswith("+"):
                is_in_progress = True
                user_input = user_input[:-1].strip()

            action_dict = json.loads(user_input)
            
            # 濡傛灉浣跨敤浜?"+" 涓?JSON 涓湭鏄惧紡鎸囧畾鐘舵€侊紝鍒欐敞鍏?in_progress
            if is_in_progress and "task_status" not in action_dict:
                action_dict["task_status"] = "in_progress"

            print(f"鉁?鎸囦护宸叉帴鏀? {json.dumps(action_dict, ensure_ascii=False)}")
            return action_dict
        except json.JSONDecodeError:
            print("鉂?杈撳叆鏍煎紡閿欒锛岃纭繚杈撳嚭涓虹函 JSON (渚嬪: {\"action\": \"click\", \"target\": \"e1\"})")
            print("馃挕 鎻愮ず: 閫€鍑鸿杈撳叆 'exit'锛屽姝ヨ繛缁搷浣滃彲鍦ㄥ懡浠ゆ湯灏惧姞 '+' (濡? {\"action\":\"click\", \"target\":\"e1\"}+)")
        except EOFError:
            print("馃洃 杈撳叆娴佷腑鏂€?)
            return {"action": "wait", "value": "2000"}

def get_current_token_usage() -> int:
    return _SESSION_TOKEN_USAGE
