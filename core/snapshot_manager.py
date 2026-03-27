import asyncio
import json
import os
import time
import uuid

# [v1.8 优化A] 增量扫描：追踪上次执行全谱业务异常扫描时的页面 URL
# 只在 URL 发生变化后的第一次快照中触发三重扫描，其余时跳过
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
        # 统一 DEBUG 前缀以受控输出
        if "DEBUG:" not in msg_str.upper() and not msg_str.startswith(" ["):
            msg_str = f"DEBUG: {msg_str}"
        
        if logger:
            logger(msg_str)
        else:
            print(msg_str, flush=True)

    # 确保 tmp 目录存在
    tmp_dir = os.path.join(_project_root(), 'artifacts', 'tmp')
    os.makedirs(tmp_dir, exist_ok=True)

    timestamp = time.strftime("%m%d_%H%M%S")
    temp_filename = f"snapshot_{timestamp}_{uuid.uuid4().hex[:4]}.json"
    temp_file = os.path.join(tmp_dir, temp_filename)
    
    current_page_url = target_url # 初始猜测

    try:
        # 1. 预热与同步：尝试使用 Playwright 智能等待机制
        page = None
        try:
            from core.verification_engine import get_playwright_page
            # 如果上层没传目标 URL，尝试先用模糊匹配获取 page
            page = await get_playwright_page(target_url=current_page_url)
            if page:
                try:
                    # 等待网络空闲（前端请求完成），最多等 2 秒，能有效处理 SPA 渲染
                    await page.wait_for_load_state('networkidle', timeout=2000)
                    if not current_page_url: current_page_url = page.url
                except Exception:
                    pass  # 如果遇到长直连导致 networkidle 超时，直接放行抓取
            else:
                # [v1.8 优化B] 降级路径：从 1.0s 缩短至 0.1s，减少不必要阻塞
                await asyncio.sleep(0.1)
        except Exception as e:
            log(f"DEBUG: 智能等待降级: {str(e)}")
            await asyncio.sleep(1.0)
        
        # [v1.9.2 优化] 异常哨兵：改进增量扫描策略
        # 1. 尝试获取底层截获的原生浏览器弹窗 (Alert/Confirm)
        native_dialog = ""
        try:
            from core.verification_engine import get_last_dialog_message
            native_dialog = get_last_dialog_message() or ""
        except:
            pass

        global_alerts = native_dialog
        try:
            if page:
                # [v1.9.2 优化] 基础选择器扫描改为必做，仅 Keyword 扫描保留增量策略
                # 这样可以实时捕捉同 URL 下产生的业务弹窗
                custom_keywords = os.getenv('AGENT_DETECTION_KEYWORDS', '')
                default_keywords = "Unauthorized,Denied,Forbidden,403,404,500,无权限,授权,申请,报错,失败,错误,系统繁忙"
                all_kws = list(set([k.strip() for k in (default_keywords + "," + custom_keywords).split(',') if k.strip()]))
                
                # 更新 URL 记录
                global _last_scanned_url
                current_url_for_scan = current_page_url or (page.url if page else "")
                is_url_changed = (current_url_for_scan != _last_scanned_url)

                # [v1.9.5 优化] 业务异常识别：移除 URL 变更限制，确保每一轮都能捕捉弹窗
                eval_script = f"""() => {{
                    try {{
                        const selectors = [
                            '.ant-message-notice-content', 
                            '.ant-notification-notice-message',
                            '.ant-notification-notice-description',
                            '.el-message__content',
                            '.el-notification__group',
                            '.toast-message',
                            '.modal-body',
                            '.alert-content',
                            '[role="alert"]',
                            '[role="status"]',
                            '[role="dialog"]',
                            '.ant-modal-confirm-content'
                        ];
                        const found = [];
                        
                        // 1. 选择器探测 (必做)
                        selectors.forEach(s => {{
                            document.querySelectorAll(s).forEach(el => {{
                                const txt = el.innerText.trim();
                                if (txt && !found.includes(txt)) found.push(txt);
                            }});
                        }});
                        
                        // 2. 视觉覆盖物探测 (必做)
                        const floatingEls = Array.from(document.querySelectorAll('body *')).filter(el => {{
                            try {{
                                const style = window.getComputedStyle(el);
                                return (style.position === 'fixed' || style.position === 'absolute') && 
                                       parseInt(style.zIndex) > 500 && 
                                       el.innerText.trim().length > 0 && 
                                       el.innerText.trim().length < 200 &&
                                       el.offsetWidth > 50 && el.offsetHeight > 20 &&
                                       style.display !== 'none' &&
                                       style.visibility !== 'hidden' &&
                                       parseFloat(style.opacity) > 0.1;
                            }} catch(e) {{ return false; }}
                        }});
                        floatingEls.forEach(el => {{
                            const txt = el.innerText.trim();
                            if (!found.some(f => f.includes(txt) || txt.includes(f))) {{
                                found.push("[Floating] " + txt);
                            }}
                        }});

                        // 3. 关键字广谱扫描 (实时，覆盖 SPA 异步弹窗)
                        const keywords = {json.dumps(all_kws)};
                        const fullText = (document.title + " " + (document.body ? document.body.innerText : "")).substring(0, 8000); 
                        keywords.forEach(kw => {{
                            if (fullText.includes(kw)) {{
                                if (!found.some(f => f.includes(kw))) {{
                                    found.push("[Keyword Match] " + kw);
                                }}
                            }}
                        }});

                        return found.join(' | ');
                    }} catch (e) {{
                        return "ERROR in evaluate: " + e.message;
                    }}
                }}"""
                scan_res = await asyncio.wait_for(page.evaluate(eval_script), timeout=2.0)
                if scan_res:
                    global_alerts = (global_alerts + " | " + scan_res).strip(" | ")
                
                # 更新 URL 记录
                _last_scanned_url = current_url_for_scan
        except Exception as e:
            log(f"DEBUG: 异常探测抛错: {str(e)}")
        
        env = os.environ.copy()
        env['AGENT_BROWSER_HEADED'] = 'true'
        # 优先使用当前环境设置的端口和 Profile
        port = os.getenv('AGENT_BROWSER_PORT', '3030')
        profile_name = os.getenv('AGENT_BROWSER_PROFILE', 'browser_profile')
        profile_path = os.path.join(os.getcwd(), 'artifacts', profile_name)
        
        # 将最新的端口 and 路径写回环境，确保子进程可见
        env['AGENT_BROWSER_PORT'] = port

        max_attempts = 3
        effective_snapshot = ""
        raw_output = ""

        # [v1.9 Batch 模式] 使用 batch 命令执行 snapshot，保留单次 IPC 调用的性能收益
        batch_commands = json.dumps([
            ["snapshot", "-i", "-C", "-c", "--json"]
        ])
        cmd_base = 'npx.cmd' if os.name == 'nt' else 'npx'
        cmd = f'{cmd_base} --no-install agent-browser --profile "{profile_path}" batch --json'
        # [v1.9.5] 技术日志标记，确保受控输出
        log(f"DEBUG: [v1.9] 使用 batch/snapshot 模式 (Port: {port})")

        for attempt in range(max_attempts):
            log(f"DEBUG: Batch 快照请求 (Try: {attempt+1}/{max_attempts})...")
            
            try:
                import subprocess
                proc = subprocess.run(
                    cmd,
                    input=batch_commands,       # 通过 stdin 传入命令 JSON
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    env=env,
                    shell=True,
                    text=True,
                    encoding='utf-8',
                    errors='ignore',
                    timeout=35.0
                )
                
                stdout_str = proc.stdout.strip()
                stderr_str = proc.stderr.strip()
                raw_output = stdout_str
                
                if proc.returncode != 0:
                    if '10048' in stderr_str or 'Address already in use' in stderr_str:
                        import random
                        wait_sec = 3.0 + random.random() * 2.0
                        log(f"DEBUG: 检测到端口冲突 (10048)，等待 {wait_sec:.1f}s 避让...")
                        await asyncio.sleep(wait_sec)
                    log(f"DEBUG: 快照失败 (code: {proc.returncode}): {stderr_str[:200]}")
                    continue

                if not stdout_str:
                    log("DEBUG: 无快照输出，重试中...")
                    continue

                # 解析 batch 输出：JSON 数组，提取最后一条（snapshot）的 result
                try:
                    # 找第一个 [ 到最后一个 ]
                    arr_start = stdout_str.find('[')
                    arr_end = stdout_str.rfind(']')
                    if arr_start == -1 or arr_end == -1:
                        log("DEBUG: batch 输出不含 JSON 数组，降级重试...")
                        continue
                    
                    batch_results = json.loads(stdout_str[arr_start:arr_end+1])
                    # 最后一条为 snapshot 命令结果
                    snap_result_obj = batch_results[-1]
                    
                    if not snap_result_obj.get('success', False):
                        err = snap_result_obj.get('error', '未知错误')
                        log(f"DEBUG: snapshot 命令失败: {err}")
                        if attempt < max_attempts - 1:
                            await asyncio.sleep(2.0 + attempt)
                        continue

                    snap_data = snap_result_obj.get('result', {})
                    content = snap_data.get('snapshot', '')
                    detected_url = snap_data.get('origin', '') or snap_data.get('url', '')
                    refs_dict = snap_data.get('refs', {})

                    # 与旧版逻辑一致：只拒绝真正空白的 (empty page)
                    if not content or content == "(empty page)":
                        log(f"DEBUG: 页面完全空白 (empty page)，等待 2s 渲染...")
                        await asyncio.sleep(2.0)
                        continue

                    # 构造与旧版兼容的 raw_output 格式供 Trace 系统使用
                    compat_dict = {
                        "success": True,
                        "data": {
                            "snapshot": content,
                            "url": detected_url,
                            "refs": refs_dict
                        }
                    }
                    with open(temp_file, 'w', encoding='utf-8') as f:
                        json.dump(compat_dict, f, indent=2, ensure_ascii=False)
                    
                    raw_output = json.dumps(compat_dict, ensure_ascii=False)
                    effective_snapshot = content
                    if detected_url:
                        current_page_url = detected_url
                    log(f" [OK] Batch 快照抓取成功 (URL: {current_page_url}, refs: {len(refs_dict)})")
                    break

                except (json.JSONDecodeError, IndexError, KeyError) as parse_err:
                    log(f"DEBUG: batch 输出解析失败: {parse_err}. 原始: {stdout_str[:300]}")
                    
            except subprocess.TimeoutExpired:
                log(f"DEBUG: batch 命令执行超时 (35s)")
            except Exception as e:
                log(f"DEBUG: 执行异常: {str(e)}")
            
            if attempt < max_attempts - 1:
                await asyncio.sleep(2.0 + attempt)  # 递增等待时间

        if not effective_snapshot:
            log(f"最终快照提取失败，可能影响后续决策。")
            return {'aria_text': 'Timeout', 'raw': raw_output, 'global_alerts': global_alerts, 'snapshot_id': 'error'}

        snapshot_id = os.path.splitext(temp_filename)[0]
        return {'aria_text': effective_snapshot, 'raw': raw_output, 'global_alerts': global_alerts, 'snapshot_id': snapshot_id}

    except Exception as e:
        log(f"快照组件异常: {str(e)}")
        return {'aria_text': '', 'raw': '', 'global_alerts': '', 'snapshot_id': 'error'}
