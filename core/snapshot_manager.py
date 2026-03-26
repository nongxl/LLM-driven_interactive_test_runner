import asyncio
import json
import os
import time
import uuid

def _project_root():
    """返回项目根目录（package.json 所在位置）"""
    return os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))

async def get_snapshot(logger=None, target_url=None):
    """
    异步获取页面快照，使用 asyncio 子进程管理确保可靠超时。
    """
    def log(msg):
        if logger:
            logger(msg)
        else:
            print(msg, flush=True)

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
                await asyncio.sleep(1.0)  # 获取 page 失败的降级方案
        except Exception as e:
            log(f"DEBUG: 智能等待降级: {str(e)}")
            await asyncio.sleep(1.0)
        
        # [NEW] 异常哨兵：广谱探测全局 Toast/Alert/Business Error
        global_alerts = ""
        try:
            if page:
                # 从环境变量获取自定义关键词，合并默认关键词
                custom_keywords = os.getenv('AGENT_DETECTION_KEYWORDS', '')
                default_keywords = "Unauthorized,Denied,Forbidden,403,404,500,无权限,授权,申请,报错,失败,错误,系统繁忙"
                all_kws = list(set([k.strip() for k in (default_keywords + "," + custom_keywords).split(',') if k.strip()]))
                
                eval_script = f"""() => {{
                    try {{
                        const selectors = [
                            '.ant-message-notice-content', 
                            '.ant-notification-notice-message',
                            '.ant-notification-notice-description',
                            '.el-message__content',
                            '.el-notification__group',
                            '.toast-message',
                            '[role="alert"]',
                            '[role="status"]',
                            '[role="dialog"]'
                        ];
                        const keywords = {json.dumps(all_kws)};
                        const found = [];
                        
                        // 1. 选择器探测 (框架特定 & ARIA 标准)
                        selectors.forEach(s => {{
                            document.querySelectorAll(s).forEach(el => {{
                                const txt = el.innerText.trim();
                                if (txt && !found.includes(txt)) found.push(txt);
                            }});
                        }});
                        
                        // 2. 视觉覆盖物探测 (高 z-index)
                        const floatingEls = Array.from(document.querySelectorAll('body *')).filter(el => {{
                            try {{
                                const style = window.getComputedStyle(el);
                                return (style.position === 'fixed' || style.position === 'absolute') && 
                                       parseInt(style.zIndex) > 1000 && 
                                       el.innerText.trim().length > 0 && 
                                       el.innerText.trim().length < 200 &&
                                       el.offsetWidth > 0 && el.offsetHeight > 0 &&
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

                        // 3. 关键词广谱扫描 (Title & Visible Content)
                        const fullText = (document.title + " " + (document.body ? document.body.innerText : "")).substring(0, 5000); 
                        keywords.forEach(kw => {{
                            if (fullText.includes(kw)) {{
                                // 如果关键词出现在文本中，且尚未被捕捉
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
                global_alerts = await asyncio.wait_for(page.evaluate(eval_script), timeout=3.0)
        except Exception as e:
            log(f"DEBUG: 异常探测抛错: {str(e)}")
        
        env = os.environ.copy()
        env['AGENT_BROWSER_HEADED'] = 'true'
        # 优先使用当前环境设置的端口和 Profile
        port = os.getenv('AGENT_BROWSER_PORT', '3030')
        profile_name = os.getenv('AGENT_BROWSER_PROFILE', 'browser_profile')
        profile_path = os.path.join(os.getcwd(), 'artifacts', profile_name)
        
        # 将最新的端口和路径写回环境，确保子进程可见
        env['AGENT_BROWSER_PORT'] = port

        max_attempts = 3
        effective_snapshot = ""
        raw_output = ""

        # Windows 下使用 npx.cmd
        cmd_base = 'npx.cmd' if os.name == 'nt' else 'npx'

        for attempt in range(max_attempts):
            log(f"DEBUG: 终端快照请求 (Port: {port}, Try: {attempt+1}/{max_attempts})...")
            
            # 改进命令构造：增加超时和更清晰的输出控制
            cmd = f'npx --no-install agent-browser --profile "{profile_path}" snapshot -i -C -c --json'
            
            try:
                # [Fix] 切换为同步阻塞调用，避免 asyncio 在 Windows 下处理子进程时的异常崩溃
                import subprocess
                proc = subprocess.run(
                    cmd,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    env=env,
                    shell=True,
                    text=True,
                    encoding='utf-8',
                    errors='ignore',
                    timeout=30.0
                )
                
                stdout_str = proc.stdout.strip()
                stderr_str = proc.stderr.strip()
                current_raw = stdout_str
                
                if proc.returncode != 0:
                    if '10048' in stderr_str or 'Address already in use' in stderr_str:
                        import random
                        wait_sec = 3.0 + random.random() * 2.0
                        log(f"DEBUG: 检测到端口冲突 (10048)，等待 {wait_sec:.1f}s 避让...")
                        await asyncio.sleep(wait_sec)
                    log(f"DEBUG: 快照失败 (code: {proc.returncode})")
                    continue

                if not current_raw: 
                    log("DEBUG: 无快照输出，重试中...")
                    continue

                # JSON 提取增强
                start_idx = current_raw.find('{')
                end_idx = current_raw.rfind('}')
                if start_idx != -1 and end_idx != -1:
                    json_str = current_raw[start_idx:end_idx+1]
                    try:
                        current_dict = json.loads(json_str)
                        raw_output = current_raw
                        
                        if current_dict.get('success', False):
                            snapshot_data = current_dict.get('data', {})
                            content = snapshot_data.get('snapshot', '')
                            detected_url = snapshot_data.get('url', '')
                            
                            if content and content != "(empty page)":
                                with open(temp_file, 'w', encoding='utf-8') as f:
                                    json.dump(current_dict, f, indent=2, ensure_ascii=False)
                                effective_snapshot = content
                                if detected_url: current_page_url = detected_url
                                log(f" [OK] 快照抓取成功 (URL: {current_page_url})")
                                break
                            else:
                                log("DEBUG: 页面内容为空，等待 2s 渲染...")
                                await asyncio.sleep(2.0)
                        else:
                            log(f"DEBUG: Agent 内部错误: {current_dict.get('error')}")
                    except json.JSONDecodeError:
                        log("DEBUG: JSON 解析失败")
            except subprocess.TimeoutExpired:
                log(f"DEBUG: 命令执行超时")
            except Exception as e:
                 log(f"DEBUG: 执行异常: {str(e)}")
            
            if attempt < max_attempts - 1:
                await asyncio.sleep(2.0 + attempt) # 递增等待时间

        if not effective_snapshot:
            log(f"最终快照提取失败，可能影响后续决策。")
            return {'aria_text': 'Timeout', 'raw': raw_output, 'global_alerts': global_alerts}

        return {'aria_text': effective_snapshot, 'raw': raw_output, 'global_alerts': global_alerts}


    except Exception as e:
        log(f"快照组件异常: {str(e)}")
        return {'aria_text': '', 'raw': '', 'global_alerts': ''}
