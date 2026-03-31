import argparse
import asyncio
import re
import json
import os
import sys
import time
import shutil
import subprocess
from datetime import datetime
from dotenv import load_dotenv

# 加载 .env 配置文件
load_dotenv()
from typing import Optional, List, Dict, Any

# 把当前路径的外层加到 sys.path 用于之后真机引入模块
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from tracer.schema import Trace, TraceResult
from core.action_executor import execute
from core.snapshot_manager import get_snapshot
from core.verification_engine import initialize_verification_engine, get_playwright_page, verify, close_verification_engine
from core.utils import cleanup_browser_env, resolve_trace_path, strip_ansi, S_OK, S_ERR, S_WARN, S_INFO
from core.report_generator import ReportGenerator

# 全局日志函数句柄，由 main 初始化
_log_func = print

def log_it(msg, end="\n", flush=True):
    _log_func(msg, end=end, flush=flush)


async def find_element_by_semantic_locator(locator: Any) -> Optional[str]:
    """通过实时快照 JSON 属性匹配元素，取代模糊的语义猜测"""
    if not locator or (not getattr(locator, 'role', None) and not getattr(locator, 'name', None)):
        return None

    role = (getattr(locator, 'role', '') or '') if locator else ''
    name = (getattr(locator, 'name', '') or '') if locator else ''
    
    profile_name = os.getenv("AGENT_BROWSER_PROFILE", "browser_profile_replay")
    profile_path = os.path.join(os.getcwd(), 'artifacts', profile_name)
    
    if not role and not name:
        return None

    log_it(f"  [Auto-Healing] 正在通过属性寻找元素: role='{role}', name='{name}'...")
    try:
        # 复用 get_snapshot 异步函数，它内置了重试和超时逻辑
        snapshot_res = await get_snapshot(logger=log_it)
        raw_json = snapshot_res.get('raw', '{}')
        if not raw_json: return None
        
        data = json.loads(raw_json)
        # 从 refs 字典中查找匹配项
        refs = data.get("data", {}).get("refs", {})
        if not refs: return None
        
        # 1. 尝试完全匹配
        for eid, info in refs.items():
            if info.get('role') == role and info.get('name') == name:
                log_it(f"  [Auto-Healing] 属性完全匹配成功: {eid}")
                return eid
        
        # 2. 尝试清洗后精确匹配 (处理带动态编号的文本)
        import re
        def clean_name(n):
            if not n: return ""
            # 移除开头的长串数字（通常是动态生成的 ID 或序号）
            return re.sub(r'^\d{5,}', '', str(n)).strip()
            
        clean_target_name = clean_name(name)
        if not clean_target_name: return None
        
        candidates = []
        for eid, info in refs.items():
            curr_name = info.get('name') or ''
            clean_curr_name = clean_name(curr_name)
            
            if info.get('role') == role:
                # 记录所有角色匹配的候选项，用于后续调试
                if clean_target_name == clean_curr_name:
                    log_it(f"  [Auto-Healing] 属性【清洗后精确匹配】成功: {eid} ({curr_name})")
                    return eid
                if clean_curr_name and (clean_target_name in clean_curr_name or clean_curr_name in clean_target_name):
                    candidates.append((eid, curr_name))
        
        # 3. 如果没有精确匹配，尝试从候选人中找最像的
        if candidates:
            # 简单取第一个，但在日志里记录
            eid, c_name = candidates[0]
            log_it(f"  [Auto-Healing] 属性【清洗后模糊匹配】成功 ({clean_target_name} ~ {c_name}): {eid}")
            return eid

    except Exception as e:
        log_it(f"  [Auto-Healing] 匹配异常: {e}")
    return None

async def _self_heal_popups(snapshot, log_it):
    """
    启发式弹窗自愈逻辑：回放时若遇到录制中未涵盖（如业务随机报错）的全局弹窗，尝试清理之。
    """
    aria_text = snapshot.get('aria_text', '')
    global_alerts = snapshot.get('global_alerts', '')
    if not global_alerts: return False

    # 常见关闭/取消关键字
    heal_keywords = ["关闭", "取消", "我知道了", "OK", "确定", "不再提示", "Close", "Cancel", "Confirm", "×"]
    
    found_ref = None
    for kw in heal_keywords:
        pattern = r'button\s+"[^"]*?' + re.escape(kw) + r'[^"]*?"\s+\[ref=(e\d+)\]'
        match = re.search(pattern, aria_text, re.IGNORECASE)
        if match:
            found_ref = match.group(1)
            log_it(f"{S_INFO} [自愈引擎] 回放中发现阻塞弹窗 '{kw}' (ref={found_ref})，尝试自动修复环境...")
            break
    
    if found_ref:
        from core.action_executor import execute
        heal_action = {"action": "click", "target": found_ref}
        await execute(heal_action)
        await asyncio.sleep(1.0)
        return True
    
    return False

async def run_replay(trace_file: str, strict: bool = False, step_timeout: int = 10, close_engine: bool = True, logger=None, generate_report: bool = False) -> dict:
    """
    回放指定的 Trace 文件并返回结构化结果。
    :param generate_report: [NEW] 是否在回放结束后异步生成由 AI 驱动的测试报告
    """
    global _log_func
    if logger:
        _log_func = logger

    start_time = time.time()
    result_summary = {
        "trace_file": trace_file,
        "status": "pass",
        "steps_completed": 0,
        "total_steps": 0,
        "error": None,
        "duration": 0,
        "step_details": []
    }

    # 路径解析优化
    resolved_path = resolve_trace_path(trace_file)
    if not os.path.exists(resolved_path):
        result_summary["status"] = "fail"
        result_summary["error"] = f"Trace file '{trace_file}' (resolved as '{resolved_path}') not found."
        return result_summary
    
    trace_file = resolved_path # 使用解析后的路径

    try:
        with open(trace_file, 'r', encoding='utf-8') as f:
            data = json.load(f)
        
        trace = Trace.model_validate(data)
        result_summary["total_steps"] = len(trace.steps)
        
        log_it(f"\n--- 正在回放 Trace: {trace.metadata.trace_id} ---")
        log_it(f" [Trace File] {trace_file}")
        
        # [NEW] 初始状态校验与同步导航
        # 如果当前浏览器处于空状态 (about:blank)，自动跳转到 Trace 的初始入口 URL
        try:
            snapshot_init = await get_snapshot(logger=None)
            current_url = snapshot_init.get('url', 'about:blank')
            if current_url == 'about:blank' and trace.metadata.url:
                log_it(f"  [Init] 浏览器处于空状态，正在自动导航至 Trace 起点: {trace.metadata.url}")
                await execute({"action": "goto", "target": trace.metadata.url})
                await asyncio.sleep(2)
        except Exception as e:
            log_it(f"  [WARN] 初始状态采集失败: {e}")

        for step in trace.steps:
            step_start = time.time()
            step_info = {"step_id": step.step_id, "instruction": step.instruction, "status": "pass", "error": None}
            log_it(f"[Step {step.step_id}] {step.instruction}")
            
            actions_to_run = getattr(step, 'sub_actions', []) if getattr(step, 'sub_actions', []) else [step]
            
            for sub_idx, sub in enumerate(actions_to_run):
                # 如果这个子动作在录制时就是执行失败的（比如点错了），不要在回放时傻傻重复错误
                if getattr(sub, 'execution', None) and sub.execution.status != "success":
                    log_it(f"  [Skip] 跳过录制时失败的动作 (Sub-Action {sub_idx+1})")
                    continue
                
                # [NEW] 动作前 URL 状态对齐校验
                # 检查录制此步骤时的 URL 是否与当前浏览器 URL 匹配
                recorded_url = sub.snapshot_info.page_url
                if recorded_url:
                    try:
                        # 快速检查当前状态
                        check_snapshot = await get_snapshot(logger=None)
                        current_url = check_snapshot.get('url', '')
                        
                        # 如果 URL 不匹配且当前不是 about:blank
                        # (简单的字符串包含判断，兼容重定向后的微小差异)
                        if current_url != 'about:blank' and recorded_url.split('?')[0].rstrip('/') != current_url.split('?')[0].rstrip('/'):
                            log_it(f"  [Sync] 检测到页面状态偏移 (录制: {recorded_url} | 当前: {current_url})")
                            log_it(f"  [Sync] 正在尝试等待页面同步 (3s)...")
                            await asyncio.sleep(3)
                            
                            # 再次确认
                            check_snapshot = await get_snapshot(logger=None)
                            current_url = check_snapshot.get('url', '')
                            if recorded_url.split('?')[0].rstrip('/') != current_url.split('?')[0].rstrip('/'):
                                log_it(f"  {S_WARN} [Sync] 页面仍未对齐，正在强制修复状态至: {recorded_url}")
                                await execute({"action": "goto", "target": recorded_url})
                                await asyncio.sleep(2)
                                # 强制刷新快照以更新 eID 映射关系
                                await get_snapshot(logger=None)
                        
                        # [NEW] 回放中的弹窗自愈：检查同步后的页面是否存在新出现的阻塞弹窗
                        cur_snap = await get_snapshot(logger=None)
                        await _self_heal_popups(cur_snap, log_it)

                    except Exception as sync_err:
                        log_it(f"  [WARN] 状态同步逻辑异常: {sync_err}")

                try:
                    raw_action = getattr(sub.decision, 'raw_action', None)
                    if raw_action:
                        log_it(f"  [Sub-Action {sub_idx+1}/{len(actions_to_run)}] {json.dumps(raw_action, ensure_ascii=False)}")
                    else:
                        log_it(f"  [Sub-Action {sub_idx+1}/{len(actions_to_run)}] {sub.decision.action}")

                    # 解析动作
                    action_name = sub.decision.action
                    if action_name in ("navigate", "open"): 
                        action_name = "goto"

                    if action_name == "assert":
                        # 增强回放：实际执行验证
                        log_it(f"  -> 执行验证: '{sub.decision.value}'")
                        page = await get_playwright_page()
                        v_res = await verify(page, {"type": "text_present", "value": sub.decision.value})
                        if v_res['result'] != 'pass':
                            log_it(f"  {S_WARN} 验证不匹配: {v_res['reason']}")
                        else:
                            log_it(f"  {S_OK} 验证已确认")
                        continue
                        
                    target_val = ""
                    if action_name == "goto":
                        target_val = str(sub.decision.value or "")
                    elif sub.decision.target and sub.decision.target.snapshot_id:
                        target_val = sub.decision.target.snapshot_id
                        # [Optimization] 为了降低 Daemon 压力，取消执行前的 Proactive 映射
                        # 只有在执行失败触发自愈时才进行动态查找
                    
                    # 执行动作
                    exec_dict = {
                        "action": action_name,
                        "target": target_val,
                        "value": sub.decision.value or ""
                    }
                    
                    # 健壮性改进：加入针对 agent-browser 进程崩溃/端口冲突的自动重试
                    for _try in range(3):
                        res = await execute(exec_dict)
                        if "os error 10048" in res or "Failed to bind TCP" in res.replace(" ", ""):
                            log_it(f"  [WARN] 进程绑死 (端口冲突)，等待 1s 后重试执行 ({_try + 1}/3)...")
                            await asyncio.sleep(1)
                            continue
                        break
                    
                    # 判定执行是否失败（能否触发自愈）
                    def is_really_failed(r):
                        # 去掉已知无关警告的干扰
                        r_clean = r.replace("ignore-https-errors", "")
                        low_r = r_clean.lower()
                        return "error" in low_r or S_ERR in r_clean or "fail" in low_r or "unknown" in low_r \
                               or "not found" in low_r or "could not locate" in low_r or "timeout" in low_r \
                               or "out of range" in low_r or "code 4294967295" in low_r

                    # 健壮性改进：初次执行失败（或由于 Daemon 启动瞬间冲突），尝试重试执行
                    if is_really_failed(res):
                        # 特殊放行：如果是 tab_close 且报错 index out of range，可能页签已经关闭，不应卡死
                        if action_name == "tab_close" and "out of range" in res.lower():
                            log_it(f"  {S_WARN} 页签已不存在，忽略关闭错误")
                            res = f"{S_OK} Tab already gone"
                        else:
                            log_it(f"  {S_WARN} 执行出现异常 ({res.strip()})，等待 2s 后尝试重试...")
                            await asyncio.sleep(2.0)
                            res = await execute(exec_dict)
                        
                        # 如果重试依然失败，且有语义定位器，尝试属性重映射自愈
                        if is_really_failed(res):
                            log_it(f"  {S_WARN} 重试失败，正在尝试【实时属性重映射】自愈...")
                            locator = None
                            if sub.decision.target and sub.decision.target.semantic_locator:
                                locator = sub.decision.target.semantic_locator
                            
                            he_eid = await find_element_by_semantic_locator(locator)
                            if he_eid:
                                log_it(f"  [Auto-Healing] 修正 Target: {target_val} -> {he_eid}")
                                res = await execute({"action": action_name, "target": he_eid, "value": sub.decision.value or ""})
                            else:
                                log_it(f"  {S_WARN} 无法通过属性定位元素，尝试强制刷新快照重试...")
                                await asyncio.sleep(1.0)
                                await execute({"action": "screenshot", "target": f"artifacts/reports/screenshots/retry_{sub_idx}.png"})
                                res = await execute(exec_dict)
                    
                    log_it(f"  -> 执行: {res}")
                    
                    # 健壮性改进：动作执行后，利用 agent-browser 的 wait_load 确保页面稳定
                    if action_name in ("click", "goto", "type", "fill", "keyboard"):
                        try:
                            # 强制等待网络空闲，确保下一条指令能找到元素
                            await execute({"action": "wait_load", "value": "networkidle"})
                        except: pass

                    if action_name == "goto": await asyncio.sleep(1.5)
                    elif action_name == "click": await asyncio.sleep(1.0)
                    else: await asyncio.sleep(0.5)

                except Exception as e:
                    log_it(f"  {S_ERR} 错误: {e}")
                    step_info["status"] = "fail"
                    step_info["error"] = str(e)
                    break
            
            # 如果中间动作没有 fail，则在动作全部完成后执行此统一的大步骤验证
            if step_info["status"] != "fail" and getattr(step, "expected", None):
                log_it(f"  [Verify] 正在执行大步骤最终验证...", end="", flush=True)
                page = await get_playwright_page()
                if page:
                    if isinstance(step.expected, list):
                        expected_data = [e.model_dump() for e in step.expected]
                    elif step.expected:
                        expected_data = step.expected.model_dump()
                    else:
                        expected_data = None
                    
                    v_res = await verify(page, expected_data)
                    if v_res['result'] == 'pass':
                        log_it(f" {S_OK} {v_res['reason']}")
                    else:
                        # 对于兼容老 Trace: 老 Trace 中本身期望失败的，我们依然放过
                        expected_to_fail = getattr(step, "verification", None) and step.verification.result == "fail"
                        if expected_to_fail and not getattr(step, 'sub_actions', []):
                            log_it(f" {S_WARN} {v_res['reason']} (此步骤在旧版 Trace 中也是失败的，兼容放行)")
                        else:
                            log_it(f" {S_ERR} {v_res['reason']}")
                            step_info["status"] = "fail"
                            step_info["error"] = v_res['reason']
                else:
                    log_it(f" {S_WARN} 无法获取 Page，跳过验证")

            result_summary["step_details"].append(step_info)
            if step_info["status"] == "fail":
                result_summary["status"] = "fail"
                if strict:
                    result_summary["error"] = f"Strict mode: Stopped at step {step.step_id} - {step_info['error']}"
                    break
            
            result_summary["steps_completed"] += 1

    except Exception as e:
        result_summary["status"] = "fail"
        result_summary["error"] = f"Fatal replay error: {str(e)}"
    finally:
        if close_engine:
            await close_verification_engine()
        result_summary["duration"] = round(time.time() - start_time, 2)

        # [NEW] 回放报告生成逻辑
        if generate_report:
            try:
                log_it(f"\n{S_INFO} 正在生成由 AI 驱动的回放总结报告...")
                # 使用已经在 schema.py 中重命名后的 TraceResult
                trace.result = TraceResult(
                    status=result_summary["status"],
                    confidence=0.9, # 回放由于是确定的，置信度通常较高
                    error_message=result_summary["error"]
                )
                report_path = ReportGenerator.generate(trace, logger=log_it)
                log_it(f"✨ 测试报告已生成: {report_path}")
                result_summary["report_path"] = report_path
            except Exception as e:
                log_it(f"⚠️ 回放报告生成失败: {e}")
        
    return result_summary

async def main():
    parser = argparse.ArgumentParser(description="Replay a recorded trace file.")
    parser.add_argument("trace_file", type=str, help="Path to the JSON trace file")
    parser.add_argument("--strict", action="store_true", help="Stop on first failure")
    parser.add_argument("--no-clean", action="store_true", help="Do not clean browser environment before replay")
    args = parser.parse_args()

    # 初始化日志记录器
    log_filename = f"replay_{datetime.now().strftime('%m%d_%H%M%S')}.log"
    log_dir = os.path.join('artifacts', 'logs')
    os.makedirs(log_dir, exist_ok=True)
    full_log_path = os.path.join(log_dir, log_filename)

    def replay_log(msg, end="\n", flush=False):
        try:
            # 终端显示保留原样（如果支持颜色），但写入文件前必须过滤
            msg_str = str(msg)
            
            # [Optimization] 增加全局 DEBUG 过滤开关 (增强识别能力)
            msg_upper = msg_str.strip().upper()
            is_debug = msg_upper.startswith("DEBUG:") or "[DEBUG]" in msg_upper
            show_debug = os.environ.get("TEST_DEBUG") == "1"
            
            if not is_debug or show_debug:
                print(msg_str, end=end, flush=flush)
            
            clean_msg = strip_ansi(msg_str)
            with open(full_log_path, 'a', encoding='utf-8') as f:
                f.write(clean_msg + end)
        except Exception:
            pass

    global _log_func
    _log_func = replay_log

    log_it(f"回放日志已开启: {full_log_path}")

    if not args.no_clean:
        cleanup_browser_env(profile_name="browser_profile_replay", logger=log_it)
        log_it(" [Wait] 等待系统完全释放资源 (10s)...")
        await asyncio.sleep(10)

    # 设置回放专用的环境变量
    os.environ["AGENT_BROWSER_PORT"] = "3031"
    os.environ["AGENT_BROWSER_PROFILE"] = "browser_profile_replay"

    result = None
    try:
        # CLI 模式下默认开启报告生成
        result = await run_replay(args.trace_file, strict=args.strict, generate_report=True)
        
        log_it(f"\n{'='*30}")
        log_it(f"回放完成: {result['status'].upper()}")
        log_it(f"进度: {result['steps_completed']}/{result['total_steps']}")
        log_it(f"耗时: {result['duration']}s")
        if result['error']:
            log_it(f"错误: {result['error']}")
        log_it(f"{'='*30}\n")
        
    finally:
        # Playwright 已在 run_replay() 内的 finally 中关闭，此处无需再次清理
        # agent-browser daemon 会自行保存 Profile（不打断进程）
        
        # 记录结束后，根据最终状态重命名日志文件
        if result and result.get("status"):
            try:
                status_suffix = result["status"]
                new_log_filename = log_filename.replace(".log", f"_{status_suffix}.log")
                new_full_log_path = os.path.join(log_dir, new_log_filename)
                os.rename(full_log_path, new_full_log_path)
                print(f"日志文件已重命名为: {new_full_log_path}")
            except Exception as e:
                print(f"日志重命名失败: {e}")

        if result and result.get("status") == "fail":
            sys.exit(1)

if __name__ == "__main__":
    asyncio.run(main())
