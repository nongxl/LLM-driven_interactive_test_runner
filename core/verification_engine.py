import json
import os
import asyncio
import subprocess
import time
import sys
import uuid
from datetime import datetime
from typing import Dict, Any, Optional, Union, List
from playwright.async_api import async_playwright
from core.utils import is_port_alive, get_agent_browser_executable

_pw_context_manager = None
_pw_browser = None
_pw_lock = asyncio.Lock()
_keepalive_task: Optional[asyncio.Task] = None

# [v1.9 修复2] 重连冷却机制：记录上次重连时间，防止高频重连放大断线影响
_last_reconnect_time: float = 0.0
_RECONNECT_COOLDOWN_SECS: float = 15.0

# [v1.9.2 优化] 缓存原生弹窗内容，供快照系统读取
_last_native_dialog: Optional[str] = None
# [v3.6 优化] 缓存最后一次检测到的活跃业务页签 URL
_last_active_url: Optional[str] = None

def is_engine_connected():
    """轻量级健康检查，供交互模式快速判断"""
    global _pw_browser
    try:
        return _pw_browser is not None and _pw_browser.is_connected()
    except:
        return False

async def _keepalive_loop():
    """[v1.9 修复4] 后台保活 Task：每 20s 轻量检查 CDP 连接，主动触发重连而非等到失败。"""
    global _pw_browser, _last_reconnect_time
    while True:
        await asyncio.sleep(20)
        try:
            if _pw_browser and not _pw_browser.is_connected():
                now = time.monotonic()
                if now - _last_reconnect_time >= _RECONNECT_COOLDOWN_SECS:
                    print("  [Keepalive] CDP 连接已断开，正在后台重连...", flush=True)
                    _last_reconnect_time = now
                    await close_verification_engine()
                    await initialize_verification_engine()
        except asyncio.CancelledError:
            break
        except Exception:
            pass  # 保活失败静默处理，不影响主流程


async def initialize_verification_engine(logger=None):
    """显式初始化 Playwright 和 浏览器连接"""
    global _pw_context_manager, _pw_browser, _pw_lock, _keepalive_task

    if logger is None: logger = print
    async with _pw_lock:
        if _pw_context_manager and _pw_browser:
            # [v1.9 修复1] 心跳：改用本地状态检查，不做 CDP 往返，避免页面跳转期间误触发重连
            try:
                if _pw_browser.is_connected():
                    return True
            except:
                pass

        try:
            port = os.getenv("AGENT_BROWSER_PORT", "3030")
            profile_name = os.getenv("AGENT_BROWSER_PROFILE", "browser_profile")
            profile_path = os.path.join(os.getcwd(), 'artifacts', profile_name)

            # [Heuristic 1] 优先探测服务是否已经运行，避免重复且耗时的 npx 调用
            if is_port_alive(port):
                logger(f"  [Init] 检测到端口 {port} 已有存活服务，正在尝试复用...")
                cdp_url = f"http://127.0.0.1:{port}"
            else:
                logger(f"  [Init] 正在从 agent-browser 获取 CDP URL (Port: {port})...")
                
                env = os.environ.copy()
                env['AGENT_BROWSER_PORT'] = port
                
                # [Fix] 清理代理环境变量
                for p_var in ['http_proxy', 'https_proxy', 'HTTP_PROXY', 'HTTPS_PROXY', 'all_proxy', 'ALL_PROXY']:
                    if p_var in env: del env[p_var]

                # [Optimization] 获取最优执行路径 (优先本地 node_modules)
                cmd_base = get_agent_browser_executable()
                cmd = [cmd_base, "--profile", profile_path, "get", "cdp-url", "--json"]
                cdp_url = None

                try:
                    # [V4.1] 使用 create_subprocess_shell 并拼接命令字符串以支持 Windows shell 环境
                    if os.name == 'nt':
                        cmd_str = f'{" ".join(cmd)}'
                        proc = await asyncio.create_subprocess_shell(
                            cmd_str,
                            stdout=asyncio.subprocess.PIPE,
                            stderr=asyncio.subprocess.PIPE,
                            env=env
                        )
                    else:
                        proc = await asyncio.create_subprocess_exec(
                            *cmd,
                            stdout=asyncio.subprocess.PIPE,
                            stderr=asyncio.subprocess.PIPE,
                            env=env
                        )
                    
                    try:
                        # [Optimization] 缩短探测超时至 5.0，及时发现卡顿
                        stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=5.0)
                        stdout_str = stdout.decode('utf-8', errors='ignore').strip()
                        
                        if proc.returncode == 0:
                            try:
                                # [V3.1.1 修复] 兼容多行输出情况，提取最后一行 JSON
                                last_line = stdout_str.split('\n')[-1].strip()
                                data = json.loads(last_line)
                                if data.get('success'):
                                    cdp_url = data['data']['cdpUrl']
                                    logger(f"  [Init] 成功从 agent-browser 获取 CDP URL: {cdp_url}")
                            except:
                                pass
                    except asyncio.TimeoutError:
                        logger(f"  [Warn] 获取 CDP URL 超时 (5s)，怀疑守护进程挂起")
                        try:
                            proc.kill()
                            await proc.wait()
                        except: pass
                except asyncio.CancelledError:
                    raise
                except Exception as e:
                    logger(f"  [Error] 获取 CDP URL 过程中发生异常: {e}")

            if not cdp_url:
                # [V4.0 核心自愈] 动态获取失败，说明 3030 虽然占位但服务已死，必须强制重启
                logger(f"  [Init] 正在执行【强制自愈模式】：重启 agent-browser 守护进程...")
                cmd_base = get_agent_browser_executable()
                try:
                    # 先杀掉可能活着的僵尸进程
                    close_cmd = f'{cmd_base} --profile "{profile_path}" close'
                    cp_close = await asyncio.create_subprocess_shell(close_cmd, env=os.environ.copy())
                    await asyncio.wait_for(cp_close.wait(), timeout=5.0)
                    
                    # 重新拉起并等待
                    force_start_cmd = f'{cmd_base} --profile "{profile_path}" wait --timeout 1500'
                    await asyncio.create_subprocess_shell(force_start_cmd, env=os.environ.copy())
                    await asyncio.sleep(3.0) 
                except:
                    pass
                
                cdp_url = f"http://127.0.0.1:{port}"
                logger(f"  [Warn] 守护进程已尝试重启，直连模式: {cdp_url}")
        except Exception as e:
            logger(f"  [Error] 环境预检异常: {e}")
            return False

        try:
            if not _pw_context_manager:
                _pw_context_manager = await async_playwright().start()

            if not _pw_browser:
                # [V3.4.2 终极加固] 建立连接 (增加双层超时与强制自愈)
                max_cdp_retries = 2
                for cdp_attempt in range(1, max_cdp_retries + 1):
                    try:
                        # [Optimization] 将 CDP 握手超时缩短至 4s，减少用户等待感
                        _pw_browser = await asyncio.wait_for(
                            _pw_context_manager.chromium.connect_over_cdp(cdp_url, timeout=4000), 
                            timeout=5.0
                        )
                        logger(f"  [Init] CDP 握手成功 (尝试: {cdp_attempt})")
                        break
                    except (asyncio.TimeoutError, Exception) as cdp_err:
                        if cdp_attempt == max_cdp_retries:
                            raise cdp_err
                        logger(f"  [Warn] CDP 握手失败/超时 (4s)，准备重试...")
                        await asyncio.sleep(0.5)

                # 为所有已存在的页面挂载弹窗处理器 (此时 _pw_browser 已经成立)
                for context in _pw_browser.contexts:
                    for page in context.pages:
                        _setup_dialog_handler(page)

            # [v1.9 修复4] 启动后台保活 Task（如已存在则不重复创建）
            if _keepalive_task is None or _keepalive_task.done():
                _keepalive_task = asyncio.create_task(_keepalive_loop())

            return True
        except Exception as e:
            logger(f"  [Error] 连接 Playwright 失败: {e}")
            # 处理失败时，重置浏览器对象，防止后续逻辑（如 Keepalive）误判
            _pw_browser = None
            return False

def _setup_dialog_handler(page):
    """为 Page 挂载自动处理原生弹窗的逻辑"""
    global _last_native_dialog
    try:
        # 如果已经挂载过则不再重复挂载
        if hasattr(page, "_has_dialog_handler"): return
        
        async def handle_dialog(dialog):
            global _last_native_dialog
            _last_native_dialog = f"[Browser Dialog] {dialog.type}: {dialog.message}"
            print(f"  [Auto-Handler] 自动处理弹窗: {dialog.message}", flush=True)
            await dialog.accept()
        
        page.on("dialog", lambda d: asyncio.create_task(handle_dialog(d)))
        page._has_dialog_handler = True
    except:
        pass

def get_last_dialog_message():
    """读取并清除最后一次捕获的弹窗内容"""
    global _last_native_dialog
    msg = _last_native_dialog
    _last_native_dialog = None # 读取后重置，防止同一弹窗被重复消费
    return msg


async def get_playwright_page(target_url: Optional[str] = None, logger=None):
    """获取连接到 agent-browser 的 Playwright Page 对象，包含自动重连逻辑"""
    global _pw_browser, _pw_context_manager, _last_reconnect_time
    if logger is None: logger = print

    # [v1.9 修复1] 基础连接检查
    is_connected = False
    if _pw_browser:
        try:
            is_connected = _pw_browser.is_connected()
        except:
            pass

    if not is_connected:
        now = time.monotonic()
        if now - _last_reconnect_time < _RECONNECT_COOLDOWN_SECS:
            remaining = _RECONNECT_COOLDOWN_SECS - (now - _last_reconnect_time)
            logger(f"  [Warn] CDP 断线，冷却期内等待 {remaining:.1f}s...")
            await asyncio.sleep(min(remaining, 3.0))
        _last_reconnect_time = time.monotonic()
        await close_verification_engine()
        success = await initialize_verification_engine(logger=logger)
        if not success:
            return None

    # 页面抓取与属性验证循环
    # [V4.1] 减少重试次数，平衡响应速度与稳定性
    for attempt in range(3):
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
                    # [V4.1] 允许捕获空白页，以便支持框架的初始导航 (goto) 逻辑
                    if url and not url.startswith("chrome://"):
                        business_pages.append(p)
                except:
                    continue

            if not business_pages:
                logger(f"  [Warn] (Attempt {attempt+1}/3) 未检测到任何活跃的业务页签，请确保浏览器已打开目标系统页面...")
                await asyncio.sleep(1.5)
                continue

            if business_pages:
                _pw_page = None

                # [v3.6 优化] 智能活跃页签检测：优先抓取当前处于 Visible/Focus 状态的页面
                if not target_url and len(business_pages) > 1:
                    try:
                        # [V4.1] 为探测逻辑增加 3s 硬超时，防止因某个页签正在关闭导致的整体挂起
                        results = await asyncio.wait_for(
                            asyncio.gather(*[
                                p.evaluate("({visible: document.visibilityState === 'visible', focus: document.hasFocus()})")
                                for p in business_pages
                            ], return_exceptions=True),
                            timeout=3.0
                        )
                        
                        for idx, res in enumerate(results):
                            if isinstance(res, dict) and res.get('visible'):
                                _pw_page = business_pages[idx]
                                if res.get('focus'): # 拥有焦点的是绝对首选
                                    break
                        if _pw_page:
                            _last_active_url = _pw_page.url
                            logger(f"  [ActiveTab] 自动追踪到活跃页签: {_pw_page.url}")
                    except (asyncio.TimeoutError, Exception) as e:
                        logger(f"  [Warn] 活跃页签探测超时/异常: {e}")

                if not _pw_page and target_url:
                    for p in business_pages:
                        if p.url == target_url:
                            _pw_page = p
                            break

                if not _pw_page:
                    keywords = ['portal', 'inspect', 'navigator', 'index', 'login']
                    for p in reversed(business_pages):
                        try:
                            if any(k in p.url.lower() for k in keywords):
                                _pw_page = p
                                break
                        except:
                            continue

                if not _pw_page:
                    _pw_page = business_pages[-1]

                # 确保 handler 已挂载
                _setup_dialog_handler(_pw_page)

                try:
                    if not _pw_browser.is_connected():
                        raise ConnectionError("Browser disconnected")
                    # 仅做一次轻量的 URL 读取验证
                    _ = _pw_page.url
                    return _pw_page
                except ConnectionError:
                    raise
                except Exception as e:
                    raise ConnectionError(f"Page handle invalid: {e}")

            await asyncio.sleep(0.5)
        except (Exception, ConnectionError) as e:
            err_msg = str(e).lower()
            if any(kw in err_msg for kw in ("connection closed", "disconnected", "handle invalid", "connection lost")):
                logger(f"  [Warn] CDP 通讯中断 ({e})，正在尝试强制恢复...")
                now = time.monotonic()
                if now - _last_reconnect_time >= _RECONNECT_COOLDOWN_SECS:
                    _last_reconnect_time = now
                    await close_verification_engine()
                    success = await initialize_verification_engine(logger=logger)
                    if not success:
                        break
            await asyncio.sleep(1.0)

    return None


async def close_verification_engine():
    """清理 Playwright 资源"""
    global _pw_context_manager, _pw_browser, _pw_lock, _keepalive_task

    # 取消保活 Task
    if _keepalive_task and not _keepalive_task.done():
        _keepalive_task.cancel()
        try:
            await _keepalive_task
        except asyncio.CancelledError:
            pass
        _keepalive_task = None

    async with _pw_lock:
        if _pw_browser:
            try:
                # [V5.0] 为关闭操作增加硬超时，防止卡在僵尸连接上
                await asyncio.wait_for(_pw_browser.close(), timeout=3.0)
            except:
                pass
            _pw_browser = None
        if _pw_context_manager:
            try:
                await _pw_context_manager.stop()
            except:
                pass
            _pw_context_manager = None


async def _save_verification_debug(page, expected, actual_text, processed_full_text=None, snapshot_id=None):
    """保存断言失败时的调试信息 (HTML, TXT, PNG)"""
    try:
        # 定位 artifacts/tmp 目录
        proj_root = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
        tmp_dir = os.path.join(proj_root, 'artifacts', 'tmp')
        os.makedirs(tmp_dir, exist_ok=True)
        
        prefix = f"fail_{snapshot_id}" if snapshot_id else f"fail_{datetime.now().strftime('%m%d_%H%M%S')}_{uuid.uuid4().hex[:4]}"
        
        # 1. 保存期望与实际对比 (JSON)
        debug_info = {
            "expected": expected,
            "actual_reason_summary": actual_text,
            "timestamp": datetime.now().isoformat()
        }
        with open(os.path.join(tmp_dir, f"{prefix}.json"), "w", encoding="utf-8") as f:
            json.dump(debug_info, f, indent=2, ensure_ascii=False)
            
        # 2. 保存完整文本内容 (TXT)
        with open(os.path.join(tmp_dir, f"{prefix}.txt"), "w", encoding="utf-8") as f:
            f.write(processed_full_text if processed_full_text else actual_text)
            
        # 3. 保存 HTML 源码 (HTML)
        content = await page.content()
        with open(os.path.join(tmp_dir, f"{prefix}.html"), "w", encoding="utf-8") as f:
            f.write(content)
            
        # 4. 保存截图 (PNG)
        await page.screenshot(path=os.path.join(tmp_dir, f"{prefix}.png"), full_page=True)
        
        print(f"  [Debug] 断言现场已保存至: {prefix}.*", flush=True)
    except Exception as e:
        print(f"  [Warn] 保存调试现场失败: {e}", flush=True)


async def verify(page, expected: Union[Dict[str, Any], List[Dict[str, Any]], None], before_snapshot: Optional[Dict[str, Any]] = None, after_snapshot: Optional[Dict[str, Any]] = None, snapshot_id: Optional[str] = None) -> Dict[str, Any]:
    """统一验证接口"""
    if not expected:
        return _result("rule", "dom", "pass", 1.0, "未提供预期条件，默认通过", {})

    if isinstance(expected, list):
        results = []
        for i, exp_item in enumerate(expected):
            res = await verify(page, exp_item, before_snapshot, after_snapshot, snapshot_id)
            results.append((exp_item, res))

        all_passed = all(r["result"] == "pass" for _, r in results)
        raw_results = [r for _, r in results]
        if all_passed:
            return _result("composite", "various", "pass", 1.0, f"所有 {len(results)} 个检查点均通过", {"results": raw_results})
        else:
            failed_lines = []
            for i, (exp_item, r) in enumerate(results):
                if r["result"] != "pass":
                    t = exp_item.get("type", "?")
                    v = str(exp_item.get("value", exp_item.get("selector", "")))[:60]
                    actual = r.get("reason", "未知")
                    failed_lines.append(f"  #{i} [{t}='{v}'] → {actual}")
            reason = "部分检查点未通过:\n" + "\n".join(failed_lines)
            return _result("composite", "various", "fail", 1.0, reason, {"results": raw_results})

    exp_type = expected.get("type")
    exp_value = expected.get("value")
    selector = expected.get("selector")

    max_wait = 5.0
    interval = 0.5
    elapsed = 0.0
    last_actual = "超时未捕获状态"
    last_full_text = None

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
                full_text = await page.evaluate("""() => {
                    let text = document.body ? document.body.innerText : '';
                    const inputs = Array.from(document.querySelectorAll('input, textarea'));
                    inputs.forEach(el => {
                        if (el.placeholder) text += ' ' + el.placeholder;
                        if (el.value) text += ' ' + el.value;
                    });
                    const titles = Array.from(document.querySelectorAll('[title]'));
                    titles.forEach(el => {
                        if (el.title) text += ' ' + el.title;
                    });
                    return text;
                }""")
                last_full_text = full_text
                processed_text = "".join(full_text.split()).lower()
                
                if target in processed_text:
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
                raise

        await asyncio.sleep(interval)
        elapsed += interval

    if expected:
        sid = snapshot_id or (after_snapshot.get('snapshot_id') if after_snapshot else None)
        await _save_verification_debug(page, expected, last_actual, last_full_text, sid)

    return _result("rule", "dom", "fail", 1.0, last_actual, {})


def get_last_active_url():
    """获取最后一次快照探测到的活跃页签 URL"""
    return _last_active_url

def _result(method, source, result, confidence, reason, evidence):
    return {
        "method": method,
        "source": source,
        "result": result,
        "confidence": confidence,
        "reason": reason,
        "evidence": evidence
    }
