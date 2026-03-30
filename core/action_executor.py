import asyncio
import os
import json
import subprocess
from datetime import datetime
from core.ocr_helper import recognize_captcha
from core.utils import strip_ansi, S_OK, S_ERR, S_WARN, S_INFO

# agent-browser 本地安装路径，优先使用 node_modules 中的二进制文件
LOCAL_BIN = os.path.join(os.path.dirname(__file__), '..', 'node_modules', '.bin', 'agent-browser.cmd' if os.name == 'nt' else 'agent-browser')
if os.path.exists(LOCAL_BIN):
    AGENT_BROWSER_CMD = f'"{os.path.abspath(LOCAL_BIN)}"'
else:
    AGENT_BROWSER_CMD = 'npx.cmd' if os.name == 'nt' else 'npx'

def _project_root():
    """返回项目根目录（package.json 所在位置）"""
    return os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))

async def _run(cmd_args):
    """
    异步执行 agent-browser 子命令内容，返回 (stdout, returncode)
    使用 asyncio 提供的子进程管理，确保超时控制的可靠性。
    """
    env = os.environ.copy()
    env['AGENT_BROWSER_HEADED'] = 'true'
    env['AGENT_BROWSER_PORT'] = os.getenv('AGENT_BROWSER_PORT', '3031')
    
    profile_name = os.getenv('AGENT_BROWSER_PROFILE', 'browser_profile_replay')
    profile_path = os.path.join(os.getcwd(), 'artifacts', profile_name)
    
    # [Fix] 构造完整命令字符串
    # 如果是 npx 调用，需要中间加 'agent-browser' 参数；若是直连本地二进制，则不需要。
    if 'node_modules' in AGENT_BROWSER_CMD or 'agent-browser' in AGENT_BROWSER_CMD.lower():
        base_cmd = AGENT_BROWSER_CMD
    else:
        base_cmd = f"{AGENT_BROWSER_CMD} agent-browser"
        
    cmd_str = f'{base_cmd} --profile "{profile_path}" ' + " ".join([f'"{arg}"' if " " in arg or "-" not in arg else arg for arg in cmd_args])

    max_retries = 3
    for attempt in range(1, max_retries + 1):
        try:
            # [Fix] 切换为同步阻塞调用，避免 asyncio 在 Windows 下处理子进程时的异常崩溃
            import subprocess
            proc = subprocess.run(
                cmd_str,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                cwd=_project_root(),
                env=env,
                shell=True,
                text=True,
                encoding='utf-8',
                errors='ignore',
                timeout=45.0
            )
            
            stdout = proc.stdout.strip()
            stderr = proc.stderr.strip()
                
            # 处理输出，过滤 ANSI 并合并
            clean_stdout = strip_ansi(stdout)
            clean_stderr = strip_ansi(stderr)
            all_output = (clean_stdout + "\n" + clean_stderr).strip()
            
            # [Optimization] 精准处理 10048 端口占用
            # 只有在返回码非 0（真正无法执行）时才进行避让重试
            if proc.returncode != 0 and ("10048" in all_output or "Address already in use" in all_output or "只允许使用一次" in all_output):
                if attempt < max_retries:
                    import random
                    wait_sec = 2.0 + random.random() * 2.0
                    print(f"  [WARN] 动作执行检测到端口冲突 (真正的 10048 失败)，正在进行第 {attempt} 次避让重试 ({wait_sec:.1f}s)...", flush=True)
                    await asyncio.sleep(wait_sec)
                    continue

            # 过滤掉冗余的 daemon running 警告以及成功的 10048 探测警告
            noise_patterns = [
                "--profile, --ignore-https-errors ignored: daemon already running",
                "⚠ --profile, --ignore-https-errors ignored: daemon already running",
                "Address already in use",
                "10048",
                "只允许使用一次",
                "os error 10048"
            ]
            
            lines = all_output.split('\n')
            clean_lines = []
            for line in lines:
                if not any(pattern in line for pattern in noise_patterns):
                    clean_lines.append(line)
            all_output = "\n".join(clean_lines).strip()
            
            if proc.returncode != 0:
                return f"{S_ERR} Error (code {proc.returncode}): {all_output}"
            
            return all_output
        except subprocess.TimeoutExpired:
            return f"{S_ERR} Error: Command timed out after 45s."
        except Exception as e:
            if attempt < max_retries:
                await asyncio.sleep(1.0)
                continue
            return f"❌ Error spawning process: {str(e)}"
    
    return f"{S_ERR} Max retries reached for action execution due to conflicts."

async def execute(action):
    """
    异步根据 AI 决策执行 agent-browser 命令
    支持传入单条 dict 指令或多条 dict 组成的 list 指令。
    """
    if isinstance(action, list):
        # [NEW] 批量处理动作列表
        results = []
        for i, sub_action in enumerate(action, 1):
            res = await execute(sub_action)
            results.append(f"({i}) {res}")
        return " | ".join(results)

    if not isinstance(action, dict):
        return f"{S_ERR} Error: Action must be a dict or list of dicts, got {type(action).__name__}"

    action_type = action.get('action', '').lower()
    target = action.get('target', '')
    value = action.get('value', '')
    task_status = action.get('task_status', '')

    try:
        # [v1.9.5 优化] 处理纯状态更新指令 (No-Op Action)
        # 支持用户输入 {"task_status": "completed"} 来手动结束步骤
        if not action_type and task_status:
            return f"{S_OK} 状态同步成功: {task_status}"

        # 统一判定逻辑：如果返回内容包含错误特征，则直接透传原始信息
        def is_failed(r):
            low_r = r.lower()
            return "error" in low_r or "❌" in r or "fail" in low_r or "unknown" in low_r or "not found" in low_r

        # 1. 导航
        if action_type in ('goto', 'open'):
            res = await _run(['open', target])
            if is_failed(res): return res
            return f"{S_OK} Navigated to {target}"

        # 2. 点击
        elif action_type == 'click':
            res = await _run(['click', target])
            if is_failed(res): return res
            return f"{S_OK} Clicked {target}"

        # 3. 输入
        elif action_type in ('type', 'fill'):
            res = await _run(['fill', target, str(value)])
            if is_failed(res): return res
            return f"{S_OK} Filled {target} with '{value}'"

        # 4. 等待 (ms 或 元素)
        elif action_type == 'wait':
            res = await _run(['wait', str(value)])
            if is_failed(res): return res
            return f"{S_OK} Waited {value}"

        # 5. 滚动
        elif action_type in ('scroll', 'scrollintoview'):
            res = await _run(['scrollintoview', target])
            if is_failed(res): return res
            return f"{S_OK} Scrolled {target} into view"

        # 6. 截图
        elif action_type == 'screenshot':
            report_dir = os.path.join(_project_root(), 'artifacts', 'reports', 'screenshots')
            os.makedirs(report_dir, exist_ok=True)
            timestamp = datetime.now().strftime('%m%d_%H%M%S')
            filename = f"screenshot_{timestamp}.png"
            filepath = os.path.join('artifacts', 'reports', 'screenshots', filename)
            res = await _run(['screenshot', filepath])
            if is_failed(res): return res
            return f"{S_OK} Screenshot saved to {filepath}"

        # 7. 键盘
        elif action_type == 'keyboard':
            res = await _run(['keyboard', 'type', str(value)])
            if is_failed(res): return res
            return f"{S_OK} Keyboard type: {value}"

        # 8. 获取文本
        elif action_type == 'get_text':
            res = await _run(['get', 'text', target])
            if is_failed(res): return res
            return f"{S_OK} Text from {target}: {res}"

        # 9. 页签切换与关闭
        elif action_type in ('tab', 'switch_tab', 'tab_close'):
            # 特殊处理关闭指令
            if action_type == 'tab_close' or target == 'close':
                close_idx = value if action_type == 'tab_close' else value
                args = ['tab', 'close']
                if close_idx: args.append(str(close_idx))
                res = await _run(args)
                if is_failed(res): return res
                return f"{S_OK} Tab closed"

            if target:
                await asyncio.sleep(1.0) # 延迟等待页签列表刷新

            async def _try_tab_async(t):
                if not t:
                    return await _run(['tab'])
                else:
                    return await _run(['tab', str(t)])

            res = await _try_tab_async(target)
            
            # 失败重试逻辑 (针对 Agent-Browser 列表延迟)
            if "out of range" in res or "Error" in res or S_ERR in res:
                await asyncio.sleep(1.0)
                res = await _try_tab_async(target)

            if is_failed(res): return res
            return f"{S_OK} {res}"

        # 10. 快照
        elif action_type == 'snapshot':
            res = await _run(['snapshot', '--json'])
            if is_failed(res): return res
            return f"{S_OK} Snapshot captured (Check ARIA Tree below)"

        # 11. 加载状态等待
        elif action_type == 'wait_load':
            state = value if value else 'networkidle'
            res = await _run(['wait', '--load', state])
            if is_failed(res): return res
            return f"{S_OK} Waited for load state: {state}"

        # 12. OCR (演示用)
        elif action_type == 'ocr':
            box_output = await _run(['get', 'box', target, '--json'])
            if is_failed(res): return res
            
            box_data = json.loads(box_output).get('data')
            if not box_data:
                return f"{S_ERR} Error: Could not get box for {target}"
            
            ocr_dir = os.path.join(_project_root(), 'artifacts', 'reports', 'ocr')
            os.makedirs(ocr_dir, exist_ok=True)
            temp_shot = os.path.join('artifacts', 'reports', 'ocr', f"ocr_source_{target.replace('@','')}.png")
            await _run(['screenshot', temp_shot])
            
            full_path = os.path.join(_project_root(), temp_shot)
            result_text = recognize_captcha(full_path, box_data)
            return f"{S_OK} OCR Result for {target}: {result_text}"

        # 13. 断言 (逻辑标记)
        elif action_type == 'assert':
            return f"Assert checkpoint: '{value}'"

        # 14. 兜底透传：支持 agent-browser 所有内置命令 (hover, drag, press 等)
        else:
            args = [action_type]
            if target: args.append(target)
            if value: args.append(str(value))
            
            res = await _run(args)
            if is_failed(res): return res
            return f"{S_OK} Action '{action_type}' executed successfully: {res}"

    except Exception as e:
        return f"❌ Error in execute: {str(e)}"
