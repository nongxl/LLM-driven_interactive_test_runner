import asyncio
import json
import os
import time
import uuid

# [v1.8 优化A] 增量扫描：追踪上次执行全谱业务异常扫描时的页面 URL
_last_scanned_url: str = ""

def _project_root():
    """返回项目根目录（package.json 所在位置）"""
    return os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))

async def get_snapshot(logger=None, target_url=None):
    """
    异步获取页面快照，使用 asyncio 子进程管理确保可靠超时。
    """
    def log(msg):
        msg_str = str(msg)
        if "DEBUG:" not in msg_str.upper() and not msg_str.startswith(" ["):
            msg_str = f"DEBUG: {msg_str}"
        if logger: logger(msg_str)
        else: print(msg_str, flush=True)

    # 1. 准备环境
    tmp_dir = os.path.join(_project_root(), 'artifacts', 'tmp')
    os.makedirs(tmp_dir, exist_ok=True)
    timestamp = time.strftime("%m%d_%H%M%S")
    temp_filename = f"snapshot_{timestamp}_{uuid.uuid4().hex[:4]}.json"
    temp_file = os.path.join(tmp_dir, temp_filename)
    current_page_url = target_url

    try:
        # 2. 预热与智能等待 (使用 Playwright 引擎加速)
        page = None
        try:
            from core.verification_engine import get_playwright_page
            page = await get_playwright_page(target_url=current_page_url, logger=logger)
            if page:
                try:
                    await page.wait_for_load_state('networkidle', timeout=2000)
                    if not current_page_url: current_page_url = page.url
                except: pass
            else:
                await asyncio.sleep(0.1)
        except Exception as e:
            log(f"智能等待降级: {e}")
            await asyncio.sleep(1.0)
        
        # 3. 业务异常哨兵扫描 (ARIA 抓取之前的预检)
        global_alerts = ""
        try:
            from core.verification_engine import get_last_dialog_message
            global_alerts = get_last_dialog_message() or ""
            
            if page:
                custom_keywords = os.getenv('AGENT_DETECTION_KEYWORDS', '')
                all_kws = list(set([k.strip() for k in ("Unauthorized,Denied,Forbidden,403,404,500,无权限,授权,申请,报错,失败,错误,系统繁忙," + custom_keywords).split(',') if k.strip()]))
                
                eval_script = f"""() => {{
                    try {{
                        const selectors = ['.ant-message-notice-content', '.ant-notification-notice-message', '.el-message__content', '.el-notification__group', '[role="alert"]', '[role="dialog"]', '.ant-modal-confirm-content'];
                        const found = [];
                        selectors.forEach(s => {{
                            document.querySelectorAll(s).forEach(el => {{
                                const txt = el.innerText.trim();
                                if (txt && !found.includes(txt)) found.push(txt);
                            }});
                        }});
                        const keywords = {json.dumps(all_kws)};
                        const fullText = (document.title + " " + (document.body ? document.body.innerText : "")).substring(0, 8000); 
                        keywords.forEach(kw => {{ if (fullText.includes(kw)) found.push("[Keyword] " + kw); }});
                        return found.join(' | ');
                    }} catch (e) {{ return ""; }}
                }}"""
                scan_res = await asyncio.wait_for(page.evaluate(eval_script), timeout=2.0)
                if scan_res: global_alerts = (global_alerts + " | " + scan_res).strip(" | ")
        except Exception as e:
            log(f"异常探测抛错: {e}")

        # 4. 核心快照抓取 (Batch 模式)
        env = os.environ.copy()
        env['AGENT_BROWSER_HEADED'] = 'true'
        port = os.getenv('AGENT_BROWSER_PORT', '3030')
        profile_name = os.getenv('AGENT_BROWSER_PROFILE', 'browser_profile')
        profile_path = os.path.join(os.getcwd(), 'artifacts', profile_name)
        env['AGENT_BROWSER_PORT'] = port

        # [Fix] 清理代理环境变量
        for p_var in ['http_proxy', 'https_proxy', 'HTTP_PROXY', 'HTTPS_PROXY', 'all_proxy', 'ALL_PROXY']:
            if p_var in env: del env[p_var]

        batch_commands = json.dumps([["snapshot", "-i", "-C", "-c", "--json"]])
        from core.utils import get_agent_browser_executable
        cmd_base = get_agent_browser_executable()
        cmd = f'{cmd_base} --profile "{profile_path}" batch --json'
        
        max_attempts = 3
        effective_snapshot = ""
        raw_output = ""

        for attempt in range(max_attempts):
            log(f"Batch 快照请求 (Try: {attempt+1}/{max_attempts})...")
            try:
                # [V3.1 深度异步化] 启用异步子进程
                proc = await asyncio.create_subprocess_shell(
                    cmd,
                    stdin=asyncio.subprocess.PIPE,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE,
                    env=env
                )
                
                try:
                    stdout, stderr = await asyncio.wait_for(proc.communicate(input=batch_commands.encode('utf-8')), timeout=60.0)
                    stdout_str = stdout.decode('utf-8', errors='ignore').strip()
                    stderr_str = stderr.decode('utf-8', errors='ignore').strip()
                    raw_output = stdout_str
                    
                    if proc.returncode != 0:
                        if '10048' in stderr_str:
                            await asyncio.sleep(2.0)
                        log(f"快照失败 (code: {proc.returncode})")
                        continue

                    # 解析结果
                    arr_start = stdout_str.find('[')
                    arr_end = stdout_str.rfind(']')
                    if arr_start == -1 or arr_end == -1: continue
                    
                    results = json.loads(stdout_str[arr_start:arr_end+1])
                    snap_obj = results[-1]
                    if not snap_obj.get('success'): continue

                    data = snap_obj.get('result', {})
                    content = data.get('snapshot', '')
                    if content and content != "(empty page)":
                        effective_snapshot = content
                        current_page_url = data.get('url', current_page_url)
                        
                        # 保存兼容性数据
                        compat = {"success": True, "data": {"snapshot": content, "url": current_page_url, "refs": data.get('refs', {})}}
                        with open(temp_file, 'w', encoding='utf-8') as f: json.dump(compat, f, indent=2, ensure_ascii=False)
                        raw_output = json.dumps(compat, ensure_ascii=False)
                        log(f" [OK] Batch 快照抓取成功 (URL: {current_page_url})")
                        break
                    else:
                        await asyncio.sleep(1.0)
                except asyncio.TimeoutError:
                    log("快照抓取超时")
                    try: proc.kill()
                    except: pass
                except asyncio.CancelledError:
                    log("用户中断快照过程")
                    try: proc.kill()
                    except: pass
                    raise
            except Exception as e:
                log(f"子进程异常: {e}")
            if attempt < max_attempts - 1: await asyncio.sleep(1.0)

        if not effective_snapshot:
            return {'aria_text': 'Timeout', 'raw': raw_output, 'global_alerts': global_alerts, 'snapshot_id': 'error'}

        return {
            'aria_text': effective_snapshot, 'raw': raw_output, 
            'global_alerts': global_alerts, 'snapshot_id': os.path.splitext(temp_filename)[0],
            'url': current_page_url
        }

    except Exception as e:
        log(f"快照组件故障: {e}")
        return {'aria_text': '', 'raw': '', 'global_alerts': '', 'snapshot_id': 'error'}
