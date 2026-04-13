import os
import json
import time
import sys
import requests
import re
import asyncio
import threading
from datetime import datetime
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
from typing import Dict, Any, List, Optional
from dotenv import load_dotenv

# [V6.1] 异步输入全局设施
_input_queue = asyncio.Queue()
_input_thread_started = False

def _start_input_thread(loop):
    """启动后台输入监听线程 (传入 loop 以确保线程安全)"""
    def _input_worker():
        while True:
            try:
                line = sys.stdin.readline()
                if not line: break
                # [Thread-Safe] 使用 call_soon_threadsafe 向异步队列投放数据
                loop.call_soon_threadsafe(_input_queue.put_nowait, line.strip())
            except:
                break
    
    t = threading.Thread(target=_input_worker, daemon=True)
    t.start()

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
    log_dir = os.path.join("artifacts", "tmp", "prompts")
    os.makedirs(log_dir, exist_ok=True)
    
    timestamp = time.strftime("%H%M%S")
    msg_hash = hashlib.md5(str(messages[-1]).encode()).hexdigest()[:6]
    status = "error" if error else "ok"
    filename = f"p_{timestamp}_{model.replace('/','_')}_{msg_hash}_{status}.json"
    
    dump_data = {
        "timestamp": datetime.now().isoformat(),
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
    
    default_base_url = "https://api.openai.com/v1"
    if os.getenv("GOOGLE_API_KEY") and not os.getenv("AI_BASE_URL"):
        default_base_url = "https://generativelanguage.googleapis.com/v1beta/openai/"
        
    base_url = os.getenv("AI_BASE_URL", default_base_url)
    model = os.getenv("AI_MODEL", "gemini-1.5-pro")
    mode = os.getenv("EXECUTION_MODE", "auto" if api_key else "interactive").lower()
    proxy = os.getenv("AI_PROXY")
    
    return api_key, base_url, model, mode, proxy

async def decide_action(messages: list, allow_interactive: bool = True, force_interactive: bool = False) -> Dict[str, Any]:
    """决策入口 (已异步化，支持非阻塞交互)"""
    api_key, base_url, model, mode, proxy = _get_api_config()
    
    if force_interactive:
        return await _decide_interactive(messages, title="🛑 进入手工确认模式 (Manual Setup)")

    if mode == "auto" and api_key:
        return await _decide_auto(messages, api_key, base_url, model, proxy, allow_interactive=allow_interactive)
    else:
        if not allow_interactive:
            # [V3.3.4] 在日志中反馈原因，避免用户误判为 API 故障
            reason = "Skipped AI decision because EXECUTION_MODE=interactive" if mode == "interactive" else "AI unavailable (Key missing or mode error)"
            return {"status": "unknown", "action": "wait", "value": "2000", "reason": reason}
        return await _decide_interactive(messages, title="🤖 进入交互模式 (Manual Control)")


def query_llm(messages: List[Dict[str, str]], json_mode: bool = False, proxy: str = None, logger=None, timeout: int = 60, max_retries: int = 3) -> str:
    """通用的 LLM 调用接口"""
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
            
            if attempt == 0:
                _save_prompt_log(messages, "PENDING...", model)

            response = session.post(full_url, headers=headers, json=payload, timeout=timeout)
            response.raise_for_status()
            
            log(f"  [LLM] 请求成功 (响应: {len(response.text)} bytes)", flush=True)
            
            _save_prompt_log(messages, response.text, model)
            
            res_json = response.json()
            message = res_json["choices"][0]["message"]
            content = message.get("content", "")
            
            reasoning = message.get("reasoning_content") or message.get("reasoning") or message.get("thinking")
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
            _save_prompt_log(messages, "FAILED", model, error=last_error)
            
            if "429" in last_error:
                log(f"  [Info] 触发频率限制，等待 5s 后重试...", flush=True)
                time.sleep(5)
            elif attempt < max_retries - 1:
                log(f"  [Info] 等待 2s 后进行下一次重试...", flush=True)
                time.sleep(2)
            else:
                log(f"  [Error] 已达到最大重试次数，放弃请求。", flush=True)

    return f"Error: {last_error}"

async def _decide_auto(messages: List[Dict[str, str]], api_key: str, base_url: str, model: str, proxy: str = None, allow_interactive: bool = True) -> Dict[str, Any]:
    """自动模式"""
    show_thoughts = int(os.environ.get("SHOW_THOUGHTS", "0"))
    if show_thoughts != 0:
        print(f"🤖 [自动/思考模式] 正在请求推理决策 (Model: {model})...")
    
    # [V6.3] 异步包装同步的 HTTP 请求，防止阻塞心跳检测
    try:
        response_json = await asyncio.to_thread(query_llm, messages, json_mode=True, proxy=proxy)
        if not response_json or "Error:" in str(response_json):
            raise ValueError(str(response_json) if response_json else "Empty response from LLM")
        
        content = response_json
        if "```json" in content: content = content.split("```json")[1].split("```")[0].strip()
        elif "```" in content: content = content.split("```")[1].split("```")[0].strip()

        decision = json.loads(content)
        print(f"✅ 推理决策已获得: {json.dumps(decision, ensure_ascii=False)}")
        return decision
    except Exception as e:
        print(f"❌ JSON 解析失败: {str(e)}")
        if allow_interactive:
            return await _decide_interactive(messages)
        else:
            return {"status": "unknown", "action": "wait", "value": "2000", "reason": f"JSON Parse Error: {str(e)}"}

async def _decide_interactive(messages: List[Dict[str, Any]], title: str = "🤖 进入交互模式") -> Dict[str, Any]:
    """
    [V6.1 重构] 非阻塞式人工交互循环：
    在等待用户输入的同时，能够感知后台连接状态的变化。
    """
    global _input_thread_started
    from core.verification_engine import is_engine_connected
    
    if not _input_thread_started:
        loop = asyncio.get_event_loop()
        _start_input_thread(loop)
        _input_thread_started = True

    # [V6.4] 尝试从消息历史中提取最新的 ARIA 树并展示给用户
    try:
        current_content = messages[-1].get("content", "")
        aria_match = re.search(r'\[Snapshot ARIA\](.*?)\[/Snapshot ARIA\]', current_content, re.DOTALL)
        if aria_match:
            print(f"\n📄 [当前页面 ARIA 状态]\n{aria_match.group(1).strip()}\n" + "-"*30)
        else:
            goal_match = re.search(r'Current Goal: (.*?)\n', current_content)
            if goal_match:
                print(f"\n🎯 [当前目标]: {goal_match.group(1).strip()}")
    except: pass

    print("\n" + "="*50)
    print(title)
    print("💡 提示: 即使未刷新，后台也会自动尝试重连浏览器")
    print("⌨️ 快捷键: q(退出), r(立即刷新快照), 指令末尾加+号(连续模式)")
    print("="*50)

    prompt_printed = False
    last_health_status = True
    
    while True:
        current_health = is_engine_connected()
        if not current_health:
            if last_health_status:
                print(f"\n[!] {datetime.now().strftime('%H:%M:%S')} ⚠️ 连接已断开，正在等待系统自愈重启...")
                last_health_status = False
                prompt_printed = False  # 状态变更，允许重新打印提示符
            await asyncio.sleep(1.0)
            while not _input_queue.empty(): _input_queue.get_nowait()
            continue
        
        if not last_health_status:
            print(f"\n[+] {datetime.now().strftime('%H:%M:%S')} ✅ 连接已恢复，环境已就绪。")
            last_health_status = True
            prompt_printed = False  # 状态变更，允许重新打印提示符
            return {"action": "unknown", "reason": "Connection restored, refresh snapshot"}

        try:
            # [V3.3.3 优化] 仅在状态变更或首次进入时打印提示符，避免 \r 刷新干扰用户录入
            if not prompt_printed:
                print(f"\n>> 命令输入 (q退出, r刷新): ", end="", flush=True)
                prompt_printed = True
            
            user_input = await asyncio.wait_for(_input_queue.get(), timeout=2.0)
            
            if not user_input: continue
            
            low_input = user_input.lower()
            if low_input in ('exit', 'quit', 'q', ':q'):
                return {"action": "force_exit", "reason": "User requested exit"}
            if low_input in ('r', 'refresh', 's', 'snapshot', 'retry'):
                print("🔄 正在手动触发刷新...")
                return {"action": "unknown", "reason": "User requested refresh"}

            is_in_progress = False
            if user_input.endswith("+"):
                is_in_progress = True
                user_input = user_input[:-1].strip()

            try:
                action_dict = json.loads(user_input)
                if not isinstance(action_dict, (dict, list)):
                    raise ValueError("Input parsed as non-dict/list")
                
                if isinstance(action_dict, dict) and action_dict.get("action") in ("exit", "quit"):
                     return {"action": "force_exit", "reason": "User requested exit via JSON"}
                if is_in_progress and isinstance(action_dict, dict) and "task_status" not in action_dict:
                    action_dict["task_status"] = "in_progress"
                
                print(f"✅ 指令已接收: {json.dumps(action_dict, ensure_ascii=True)}")
                return action_dict
            except json.JSONDecodeError:
                # 如果不是 JSON，且没匹配到上述快捷指令，尝试作为 type 动作处理或报错
                print("❌ 格式错误，请确保输出为纯 JSON (例如: {\"action\": \"click\", \"ref\": \"e1\"}) 或使用快捷键 q(退出), r(刷新)")
        except (asyncio.TimeoutError, TimeoutError):
            # 超时则回到循环起始点，再次确认健康度
            continue
        except EOFError:
            return {"action": "force_exit", "reason": "EOF"}
        except Exception as e:
            print(f"❌ 交互异常: {e}")
            await asyncio.sleep(1.0)

def get_current_token_usage() -> Dict[str, int]:
    return _SESSION_TOKEN_USAGE
