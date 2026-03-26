import json
import os
import asyncio
import subprocess
import time
import sys
from typing import Dict, Any, Optional, Union, List
from playwright.async_api import async_playwright

_pw_context_manager = None
_pw_browser = None
_pw_lock = asyncio.Lock()

async def initialize_verification_engine():
    """显式初始化 Playwright 和 浏览器连接"""
    global _pw_context_manager, _pw_browser, _pw_lock
    
    async with _pw_lock:
        if _pw_context_manager and _pw_browser:
            # 检查存活性
            try:
                if _pw_browser.is_connected():
                    return True
            except: pass
            
        try:
            port = os.getenv("AGENT_BROWSER_PORT", "3030")
            # 优先使用 AGENT_BROWSER_PROFILE 环境变量，否则 fallback
            profile_name = os.getenv("AGENT_BROWSER_PROFILE", "browser_profile")
            profile_path = os.path.join(os.getcwd(), 'artifacts', profile_name)
            
            print(f"  [Init] 正在从 agent-browser 获取 CDP URL (Port: {port}, Profile: {profile_name})...", flush=True)
            
            env = os.environ.copy()
            env['AGENT_BROWSER_PORT'] = port
            
            # 使用 npx 获取 CDP URL
            cmd_base = 'npx.cmd' if os.name == 'nt' else 'npx'
            cmd = f'{cmd_base} agent-browser --profile "{profile_path}" get cdp-url --json'
            cdp_url = None
            
            try:
                proc = subprocess.run(
                    cmd,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    env=env,
                    shell=True,
                    text=True,
                    encoding='utf-8',
                    errors='ignore',
                    timeout=15.0
                )
                
                stdout_str = proc.stdout.strip()
                if proc.returncode == 0:
                    try:
                        data = json.loads(stdout_str)
                        if data.get('success'):
                            cdp_url = data['data']['cdpUrl']
                            print(f"  [Init] 成功从 agent-browser 获取 CDP URL: {cdp_url}")
                    except: pass
            except: pass

            if not cdp_url:
                cdp_url = f"http://127.0.0.1:{port}"
                print(f"  [Warn] 无法动态获取 CDP URL，尝试直连: {cdp_url}")
        except Exception as e:
            print(f"  [Error] 获取 CDP URL 异常: {e}")
            return False

        try:
            if not _pw_context_manager:
                _pw_context_manager = await async_playwright().start()
            
            if not _pw_browser:
                _pw_browser = await _pw_context_manager.chromium.connect_over_cdp(cdp_url, timeout=15000)
            return True
        except Exception as e:
            print(f"DEBUG Error connecting to Playwright: {e}")
            return False

async def get_playwright_page(target_url: Optional[str] = None):
    """获取连接到 agent-browser 的 Playwright Page 对象，包含自动重连逻辑"""
    global _pw_browser, _pw_context_manager
    
    # 1. 基础连接检查
    is_connected = False
    if _pw_browser:
        try:
            is_connected = _pw_browser.is_connected()
        except: pass
    
    if not is_connected:
        await close_verification_engine()
        success = await initialize_verification_engine()
        if not success: return None
    
    # 2. 页面抓取与属性验证循环
    for attempt in range(5):
        try:
            if not _pw_browser or not _pw_browser.is_connected():
                raise ConnectionError("CDP Connection lost")

            all_pages = []
            for context in _pw_browser.contexts:
                all_pages.extend(context.pages)
            
            business_pages = []
            for p in all_pages:
                try:
                    url = p.url
                    if url and not url.startswith("chrome://"): 
                        business_pages.append(p)
                except: continue

            if business_pages:
                _pw_page = None
                
                # 优先匹配完全一致的 URL
                if target_url:
                    for p in business_pages:
                        if p.url == target_url:
                            _pw_page = p
                            break
                
                # 其次匹配业务关键词
                if not _pw_page:
                    keywords = ['portal', 'inspect', 'navigator', 'index', 'login']
                    for p in reversed(business_pages):
                        try:
                            if any(k in p.url.lower() for k in keywords):
                                _pw_page = p
                                break
                        except: continue
                
                # 兜底
                if not _pw_page:
                    _pw_page = business_pages[-1] 

                try:
                    # 探查连接存活性（心跳）
                    await _pw_page.title()
                    return _pw_page
                except:
                    raise ConnectionError("Page handle invalid")
            
            await asyncio.sleep(1.0)
        except (Exception, ConnectionError) as e:
            err_msg = str(e).lower()
            if "connection closed" in err_msg or "disconnected" in err_msg or "handle invalid" in err_msg:
                print(f"  [Warn] CDP 通讯中断 ({e})，正在尝试强制恢复...")
                await close_verification_engine()
                success = await initialize_verification_engine()
                if not success: break
            await asyncio.sleep(1.0)
            
    return None

async def close_verification_engine():
    """清理 Playwright 资源"""
    global _pw_context_manager, _pw_browser, _pw_lock
    async with _pw_lock:
        if _pw_browser:
            try:
                await _pw_browser.close()
            except: pass
            _pw_browser = None
        if _pw_context_manager:
            try:
                await _pw_context_manager.stop()
            except: pass
            _pw_context_manager = None

async def verify(page, expected: Union[Dict[str, Any], List[Dict[str, Any]], None], before_snapshot: Optional[Dict[str, Any]] = None, after_snapshot: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """统一验证接口"""
    if not expected:
        return _result("rule", "dom", "pass", 1.0, "未提供预期条件，默认通过", {})

    if isinstance(expected, list):
        results = []
        for i, exp_item in enumerate(expected):
            res = await verify(page, exp_item, before_snapshot, after_snapshot)
            results.append(res)
        
        all_passed = all(r["result"] == "pass" for r in results)
        if all_passed:
            return _result("composite", "various", "pass", 1.0, f"所有 {len(results)} 个检查点均通过", {"results": results})
        else:
            failed = [f"#{i}[{r.get('reason')}]" for i, r in enumerate(results) if r["result"] != "pass"]
            return _result("composite", "various", "fail", 1.0, f"部分检查点未通过: {', '.join(failed)}", {"results": results})

    exp_type = expected.get("type")
    exp_value = expected.get("value")
    selector = expected.get("selector")

    max_wait = 5.0
    interval = 0.5
    elapsed = 0.0
    last_actual = "超时未捕获状态"

    while elapsed < max_wait:
        try:
            if exp_type == "url_contains":
                url = page.url
                last_actual = f"URL={url}"
                if exp_value in url:
                    return _result("rule", "dom", "pass", 1.0, f"URL 包含 '{exp_value}'", {"url": url})
            
            elif exp_type == "url_equals":
                url = page.url
                last_actual = f"URL={url}"
                if url == exp_value:
                    return _result("rule", "dom", "pass", 1.0, f"URL 完全匹配 '{exp_value}'", {"url": url})
                    
            elif exp_type == "title_contains":
                title = await page.title()
                last_actual = f"Title={title}"
                if exp_value in title:
                    return _result("rule", "dom", "pass", 1.0, f"Title 包含 '{exp_value}'", {"title": title})
                    
            elif exp_type == "text_present":
                target = "".join(str(exp_value).split()).lower()
                full_text = await page.evaluate("() => (document.body ? document.body.innerText : '').replace(/\\s+/g, '')")
                full_text = full_text.lower()
                if target in full_text:
                    return _result("rule", "dom", "pass", 1.0, f"找到文本 '{exp_value}'", {})
                last_actual = "页面中未找到该文本"

            elif exp_type == "element_visible":
                target = selector or exp_value
                if await page.locator(target).is_visible():
                    return _result("rule", "dom", "pass", 1.0, f"元素 '{target}' 可见", {})
                last_actual = f"元素 '{target}' 不可见"

        except Exception as e:
            last_actual = f"评估报错: {e}"
            if "connection closed" in str(e).lower():
                raise # 抛给外层触发重连

        await asyncio.sleep(interval)
        elapsed += interval

    return _result("rule", "dom", "fail", 1.0, last_actual, {})

def _result(method, source, result, confidence, reason, evidence):
    return {
        "method": method,
        "source": source,
        "result": result,
        "confidence": confidence,
        "reason": reason,
        "evidence": evidence
    }
