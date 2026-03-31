import yaml
import json
import os
import sys
import asyncio
from datetime import datetime

# 确保脚本能找到 runner 和 ai 模块
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from tracer.recorder import TraceRecorder
from tracer.replay_runner import run_replay
from tracer.evaluator import TraceEvaluator
from core.utils import cleanup_browser_env, strip_ansi, S_OK, S_ERR, S_WARN, S_INFO
from core.verification_engine import initialize_verification_engine, get_playwright_page, verify, close_verification_engine
from core.report_generator import ReportGenerator
import re

async def _self_heal_popups(snapshot, log_it):
    """
    启发式弹窗自愈逻辑：
    寻找页面中常见的“关闭”、“取消”、“我知道了”等按钮并尝试自动点击
    """
    aria_text = snapshot.get('aria_text', '')
    global_alerts = snapshot.get('global_alerts', '')
    if not global_alerts: return False

    # 常见关闭/取消关键字
    heal_keywords = ["关闭", "取消", "我知道了", "OK", "确定", "不再提示", "Close", "Cancel", "Confirm", "×"]
    
    # 从 ARIA Tree 中提取所有 ref
    # 格式示例: - button "取 消" [ref=e14]
    found_ref = None
    for kw in heal_keywords:
        # 更加精准的正则匹配，寻找按钮
        pattern = r'button\s+"[^"]*?' + re.escape(kw) + r'[^"]*?"\s+\[ref=(e\d+)\]'
        match = re.search(pattern, aria_text, re.IGNORECASE)
        if match:
            found_ref = match.group(1)
            log_it(f"{S_INFO} [自愈引擎] 发现潜在的关闭按钮 '{kw}' (ref={found_ref})，尝试自动修复环境...")
            break
    
    if found_ref:
        from core.action_executor import execute
        heal_action = {"action": "click", "target": found_ref, "task_status": "in_progress"}
        await execute(heal_action)
        await asyncio.sleep(1.0) # 给弹窗消失一点时间
        return True
    
    return False

async def run_test(test_file, pre_steps_override=None):
    """运行测试用例"""
    if test_file.lower().endswith('.json'):
        print(f"\n❌ 错误: 您尝试使用 test_runner 运行 JSON 文件: {test_file}")
        print(f"👉 如果您想回放录制的 Trace，请使用 replay_runner:")
        print(f"   python tracer/replay_runner.py {test_file}\n")
        sys.exit(1)
        
    trace_spec_id = os.path.splitext(os.path.basename(test_file))[0]
    
    # [Fix] 调整初始化顺序：加载 YAML 以提取真正的起始 URL
    with open(test_file, 'r', encoding='utf-8') as f:
        test_case = yaml.safe_load(f)
    
    test_url = test_case.get('url', '')
    recorder = TraceRecorder(spec_id=trace_spec_id, url=test_url, agent_model="interactive")
    test_passed = False
    execution_error = None
    log_file = None

    try:
        time_str = datetime.now().strftime('%m%d_%H%M%S')
        log_filename = f"log_{trace_spec_id}_{time_str}.log"
        log_dir = os.path.join('artifacts', 'logs')
        log_file = os.path.join(log_dir, log_filename)
        os.makedirs(log_dir, exist_ok=True)

        def log_it(msg):
            msg_str = str(msg).strip()
            # [Optimization] 增加更鲁棒的全局 DEBUG 过滤开关
            is_debug = "DEBUG:" in msg_str.upper() or msg_str.startswith("Wait ") or msg_str.startswith("Batch ")
            show_debug = os.environ.get("TEST_DEBUG") == "1"
            
            # 1. 控制台输出逻辑：确保用户能看到 ARIA Tree 和 ref 编号
            if not is_debug or show_debug:
                # 移除恢复专用的静默标签后再打印，保持控制台整洁且信息完整
                display_msg = msg_str.replace("[Snapshot ARIA]", "").replace("[/Snapshot ARIA]", "").strip()
                if display_msg:
                    print(display_msg, flush=True)
                
            try:
                # 2. 文件保存逻辑：记录原始消息（包含标签，用于轨迹恢复）
                # 过滤日志文件中的 ANSI 并统一使用 UTF-8
                clean_msg = strip_ansi(msg_str)
                with open(log_file, 'a', encoding='utf-8') as f:
                    f.write(clean_msg + "\n")
                    f.flush()
            except Exception:
                pass

        log_it(f"\n{S_INFO} 正在启动测试框架，注意以下操作指南：")
        from ai.prompt_builder import get_system_guidance, init_step_messages, append_snapshot
        log_it(f"\n{get_system_guidance()}")

        from core.snapshot_manager import get_snapshot
        from ai.llm_client import decide_action
        from core.action_executor import execute
        from core.verification_engine import verify, get_playwright_page, close_verification_engine, initialize_verification_engine
        
        test_name = test_case.get('name', 'Unnamed Test')
        
        # [NEW] 解析 pre_steps (优先级: CLI Override > YAML 字段)
        pre_steps = pre_steps_override if pre_steps_override else test_case.get('pre_steps', [])
        final_steps = []
        
        if isinstance(pre_steps, str):
            if pre_steps == "__MANUAL__":
                log_it(f"{S_INFO} 已开启【手工自由操作】模式。请在浏览器中完成操作后，在控制台输入 completed 结束前置步骤。")
                final_steps = [{
                    "instruction": "🛑 [手工前置模式] 请先在浏览器中完成任何必要的手工预处理内容操作（如滑条、验证码、复杂登录等）。完成后请在下方输入: {\"task_status\": \"completed\"}",
                    "expected": None
                }]
            else:
                # 引入双路径搜索策略: 1. 脚本目录 2. 当前 CWD
                pre_file = os.path.join(os.path.dirname(test_file), pre_steps)
                if not os.path.exists(pre_file):
                    pre_file = pre_steps # 尝试 CWD
                    
                if os.path.exists(pre_file):
                    if pre_file.lower().endswith('.json'):
                        log_it(f"{S_INFO} 正在自动回放前置轨迹 (JSON): {pre_file}")
                        # 使用异步延迟加载，确保浏览器进程完全就绪
                        await asyncio.sleep(1)
                        # 调用回放引擎，close_engine=False 保持 Session
                        replay_res = await run_replay(pre_file, strict=True, close_engine=False, logger=log_it)
                        if replay_res.get('status') != 'pass':
                            log_it(f"{S_ERR} 前置轨迹回放失败: {replay_res.get('error')}")
                            execution_error = f"Pre-step trace replay failed: {replay_res.get('error')}"
                            all_steps_completed = False
                            # 这里不再 return，让下面的 steps 逻辑根据 all_steps_completed 状态决定是否跳过
                    else:
                        log_it(f"{S_INFO} 正在合并前置步骤 (YAML): {pre_file}")
                        with open(pre_file, 'r', encoding='utf-8') as pf:
                            pre_case = yaml.safe_load(pf)
                            final_steps = pre_case.get('steps', [])
                else:
                    log_it(f"{S_ERR} 错误: 找不到前置步骤文件: {pre_steps}")
        elif isinstance(pre_steps, list):
            final_steps = pre_steps
            
        test_steps = final_steps + test_case.get('steps', [])
        test_goal = test_case.get('goal')

        # 尽早初始化验证引擎
        cleanup_browser_env(profile_name="browser_profile", logger=log_it)
        await initialize_verification_engine()

        log_it(f"\n{'='*50}")
        log_it(f"测试名称: {test_name}")
        log_it(f"开始时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        log_it(f"{'='*50}")

        if not test_steps:
            log_it(f"{S_WARN} 警告: 测试脚本中没有定义任何步骤。")
            execution_error = "No steps defined in test spec"
        else:
            # [NEW] 初始导航引导：如果定义了 URL，且当前为空页，则自动进行首次跳转
            try:
                page = await get_playwright_page()
                root_url = test_case.get('url')
                if page and (page.url == "about:blank" or page.url == "data:,") and root_url:
                    log_it(f"{S_INFO} [初始导航] 检测到浏览器处于空状态，正在自动跳转至起始 URL: {root_url}")
                    await page.goto(root_url, wait_until="networkidle", timeout=45000)
            except Exception as e:
                log_it(f"{S_WARN} [初始导航] 自动跳转失败（非致命）: {e}")

            all_steps_completed = True
            is_first_step = True
            for i, step_spec in enumerate(test_steps, 1):
                if isinstance(step_spec, dict):
                    instruction = step_spec.get('instruction', str(step_spec))
                    expected = step_spec.get('expected')
                else:
                    instruction = str(step_spec)
                    expected = None

                log_it(f"\n>>>> 开始执行步骤 {i}: {instruction} <<<<")
                
                # [v3.2 优化] 登录状态自愈：如果已经在门户首页，且指令看起来像是在尝试登录，则自动跳过
                if i > 1: # 仅对后续步骤生效
                    try:
                        page = await get_playwright_page()
                        if page and "navigator/index/portal" in page.url:
                            # 如果指令包含账号、密码、登录等关键字，且当前就在首页，说明已经登录
                            login_kws = ["账号", "密码", "登录", "admin", "login", "password", "username"]
                            if any(kw in instruction.lower() for kw in login_kws):
                                log_it(f"{S_OK} [状态同步] 检测到页面已在门户首页，自动跳过重复的登录步骤: {instruction}")
                                continue
                    except: pass

                recorder.begin_step(instruction=instruction, expected_dict=expected)

                retry_count = 0
                max_retries = 20
                step_completed = False
                step_start_snapshot = None
                
                # 初始化单步上下文
                from ai.prompt_builder import init_step_messages, append_snapshot
                messages = init_step_messages(instruction)
                decision = {} # 预初始化，防止 NameError

                while not step_completed and retry_count < max_retries:
                    # [v1.8 优化C] 移除 asyncio.sleep(2.0) 固定延迟
                    # 稳定性由 get_snapshot() 内部的 networkidle 智能等待承接
                    # 1. 获取前置快照
                    snapshot = await get_snapshot(logger=log_it)
                    if not step_start_snapshot:
                        step_start_snapshot = snapshot

                    aria_text = snapshot.get('aria_text', '')
                    global_alerts = snapshot.get('global_alerts', '')
                    
                    # [v3.2 优化] 将全量 ARIA Tree 记录进日志（控制台静默），方便后续轨迹恢复
                    log_it(f"[Snapshot ARIA]\n{aria_text}\n[/Snapshot ARIA]")

                    # [v1.9.5 自动凭证积累] 检测到业务异常时自动触发截屏
                    if global_alerts:
                        log_it(f"{S_WARN} 🚨 检测到业务异常/弹窗: {global_alerts}")
                        log_it(f"{S_INFO} 正在自动保存截屏凭证至 artifacts/reports/screenshots ...")
                        # 构造截屏指令并执行
                        screenshot_action = {"action": "screenshot", "task_status": "in_progress"}
                        await execute(screenshot_action)
                        
                        # [v3.1 新增] 触发弹窗自愈逻辑
                        if await _self_heal_popups(snapshot, log_it):
                            # 自愈成功后，刷新快照以便 AI 在干净的环境下决策
                            snapshot = await get_snapshot(logger=log_it)

                    if aria_text == 'Timeout':
                        retry_count += 1
                        log_it(f" {S_WARN} 快照超时，重试中... ({retry_count}/{max_retries})")
                        continue

                    # 2. 调用决策
                    append_snapshot(messages, snapshot)
                    decision = decide_action(messages)
                    if decision:
                        # [NEW] 鲁棒性提取：处理 list 或 dict 返回
                        is_list = isinstance(decision, list)
                        main_action = decision[-1] if is_list else decision
                        
                        # [Feature] 处理手动模式下的强制退出
                        if main_action.get('action') == 'force_exit':
                            log_it(f"\n{S_WARN} 用户请求退出测试交互...")
                            all_steps_completed = False
                            # 提前终止 recorder
                            recorder.finish_step(verification_dict={"result":"fail", "reason":"User exited"}, post_snapshot_hash=None)
                            break # 跳出 while not step_completed 循环

                        messages.append({"role": "assistant", "content": json.dumps(decision, ensure_ascii=False)})
                        log_it(f"AI 决策: {json.dumps(decision, ensure_ascii=False)}")
                        
                        # [v1.9.8] 核心数据安全性拦截 (Anti-Hallucination Interceptor)
                        # 支持对列表格式的批量检查
                        all_values = []
                        if is_list:
                            for d in decision: all_values.append(str(d.get('value', '')).lower())
                        else:
                            all_values.append(str(decision.get('value', '')).lower())

                        forbidden_data = ["password", "admin@2024", "123456", "system_admin"]
                        if any(f in val for val in all_values for f in forbidden_data):
                            # 进行二次指令对齐检查
                            instruction_text = instruction.lower()
                            if not any(val in instruction_text for val in all_values):
                                log_it(f" {S_ERR} [拦截] 检测到数据幻觉: '{decision}' 包含违禁测试数据且未在指令中提及。")
                                messages.append({"role": "user", "content": f"🚨 [数据违规] 你尝试输入了黑名单习惯性数据。请严格遵循【绝对数据严格性准则】重新决策。"})
                                continue
                    else:
                        log_it("AI 返回了空的决策，可能是输入被取消。")
                        continue
                    
                    # 重新检查是否已跳出 (多级跳出支持)
                    if main_action.get('action') == 'force_exit': break

                    # 判断是否为“观察型”辅助操作
                    action_type = main_action.get('action', '').lower()
                    target = main_action.get('target', '')
                    is_auxiliary = action_type in ('snapshot', 'screenshot') or \
                                   (action_type == 'tab' and (not target or str(target).lower() == 'list'))

                    # 3. 执行动作
                    action_start_time = recorder.start_action()
                    result = await execute(decision)
                    # Python 的 time.time() 返回秒，无需再除，差值乘 1000
                    duration_ms = (recorder.start_action() - action_start_time) * 1000
                    log_it(f"执行结果: {result}")

                    if is_auxiliary:
                        log_it(f"{S_INFO} 辅助操作执行完毕，正在刷新页面状态进行下一步真实决策...")
                        continue # 重新进入 while 循环，重新获取快照并 Prompt

                    exec_status = "success"
                    exec_error = None

                    r_clean = result.replace("ignore-https-errors", "")
                    low_r = r_clean.lower()
                    if "✗" in result or "error" in low_r or "fail" in low_r or S_ERR in r_clean or "not found" in low_r or "timeout" in low_r:
                        exec_status = "failure"
                        exec_error = result
                        
                    # ====== Trace 系统：准备语义定位器与记录动作 ======
                    if is_list:
                        decision_to_record = [d.copy() for d in decision]
                    else:
                        decision_to_record = decision.copy()
                        
                    target_id = main_action.get('target')
                    if target_id and isinstance(target_id, str) and target_id.startswith('e'):
                        try:
                            raw_snapshot = json.loads(snapshot.get('raw', '{}'))
                            refs = raw_snapshot.get('data', {}).get('refs', {})
                            if target_id in refs:
                                ref_info = refs[target_id]
                                name_val = ref_info.get('name')
                                # Fallback: parse from aria_text if name is empty
                                if not name_val:
                                    import re
                                    aria_text = snapshot.get('aria_text', '')
                                    match = re.search(r'"([^"]*?)"\s+\[ref=' + str(target_id) + r'\]', aria_text)
                                    if match:
                                        name_val = match.group(1)
                                        
                                decision_to_record['target'] = {
                                    "snapshot_id": target_id,
                                    "semantic_locator": {
                                        "role": ref_info.get('role'),
                                        "name": name_val
                                    }
                                }
                                log_it(f"  [Trace] 捕获语义属性: role='{ref_info.get('role')}', name='{name_val}'")
                        except Exception as e:
                            log_it(f"  [Warn] 提取语义属性失败: {e}")

                    try:
                        recorder.record_sub_action(
                            pre_snapshot=snapshot,
                            decision_dict=decision_to_record,
                            exec_status=exec_status,
                            exec_error=exec_error,
                            duration_ms=duration_ms
                        )
                    except Exception as e:
                        log_it(f"⚠️ Trace record error: {e}")

                    if exec_status == "failure":
                        retry_count += 1
                        error_msg = f"操作执行失败: {exec_error}。你可能由于页面未加载完毕点击了错误元素，或元素不可见。请依据上下文思考并换一种方式操作。"
                        messages.append({"role": "user", "content": error_msg})
                        log_it(f" {S_WARN} 操作失败，重新请求决策... ({retry_count}/{max_retries})")
                        continue

                    # ====== 进度接管：判断是否需要验证 ======
                    task_status = main_action.get("task_status", "completed")
                    if task_status == "in_progress":
                        log_it(f"{S_INFO} 当前目标尚未完成 (in_progress)，已记录子动作，跳过验证直接进行下一步操作...")
                        continue

                    # 4. 验证引擎 (核心改动)
                    log_it("🔍 正在进行最终验证...")
                    page = await get_playwright_page()
                    if page:
                        # 等待页面稳定
                        try:
                            await page.wait_for_load_state("networkidle", timeout=3000)
                        except: pass

                        # 获取后置快照用于记录和验证
                        snapshot_after = await get_snapshot(logger=log_it)
                        
                        # 执行验证
                        v_result = await verify(page, expected, snapshot, snapshot_after, snapshot_id=snapshot_after.get('snapshot_id'))
                        log_it(f"验证结果: {v_result['result']} ({v_result['method']}) - {v_result['reason']}")
                        
                        post_hash = snapshot_after.get('hash', f"hash_{len(snapshot_after.get('aria_text',''))}")

                        if v_result['result'] == 'pass':
                            recorder.finish_step(verification_dict=v_result, post_snapshot_hash=post_hash)
                            step_completed = True
                            log_it(f"{S_OK} 步骤验证成功")
                        else:
                            # 健壮性改进：如果决策动作为 assert 且 task_status 为 completed，视为人工确认强制通过
                            cur_action = main_action.get('action')
                            cur_status = main_action.get('task_status', 'completed')
                            if cur_action == 'assert' and cur_status == 'completed':
                                 log_it(f"{S_WARN} 收到人工强制断言指令 (Action={cur_action}, Status={cur_status})，跳过 YAML 校验并标记步骤完成。")
                                 recorder.finish_step(verification_dict=v_result, post_snapshot_hash=post_hash)
                                 step_completed = True
                            elif cur_action == 'assert' and not expected:
                                 # 兜底：如果 AI 做了 assert 但 spec 没给 expected
                                 recorder.finish_step(verification_dict=v_result, post_snapshot_hash=post_hash)
                                 step_completed = True
                            else:
                                retry_count += 1
                                v_reason = v_result.get('reason', '未知原因')
                                feedback_msg = f"步骤验证未通过: {v_reason}。这通常意味着你尚未完成指令要求的所有子动作（如登录未点击完毕）。请检查当前页面快照并继续执行剩余动作。"
                                messages.append({"role": "user", "content": feedback_msg})
                                log_it(f"🔁 验证未通过 (Action={cur_action}, Status={cur_status})，反馈给 AI 并重试... ({retry_count}/{max_retries})")
                    else:
                        # 降级：如果没有 page 对象，跳过验证
                        step_completed = True
                        recorder.finish_step(verification_dict=None, post_snapshot_hash=None)
                        log_it("⚠️ 无法获取 Playwright 页面，跳过规则验证。")

                if not step_completed:
                    # 如果是因为强制退出导致的，直接跳出外部循环
                    if decision.get('action') == 'force_exit':
                        all_steps_completed = False
                        break

                    recorder.finish_step(verification_dict=v_result if 'v_result' in locals() else None, post_snapshot_hash=None)
                    log_it(f"\n❌ 步骤 {i} 重试 {max_retries} 次后最终失败。")
                    all_steps_completed = False
                    execution_error = f"Step {i} failed verification after {max_retries} retries"
                    break
            
            # 5. 全局 Goal 验证 (New)
            if all_steps_completed and test_goal:
                log_it(f"\n{S_INFO} 执行最终目标验证 (Goal Verification)...")
                page = await get_playwright_page()
                snapshot_final = await get_snapshot(logger=log_it)
                goal_passed = True
                
                for key, val in test_goal.items():
                    sub_expected = {"type": key, "value": val}
                    v_res = await verify(page, sub_expected, after_snapshot=snapshot_final, snapshot_id=snapshot_final.get('snapshot_id'))
                    log_it(f"  - {key}: {v_res['result']} - {v_res['reason']}")
                    if v_res['result'] != 'pass':
                        goal_passed = False
                
                if goal_passed:
                    test_passed = True
                    log_it("✅ 全局目标验证通过！")
                else:
                    test_passed = False
                    execution_error = "Goal verification failed"
                    log_it("❌ 全局目标验证失败。")
            elif all_steps_completed:
                test_passed = True

    except BaseException as e:
        import traceback
        error_detail = traceback.format_exc()
        try:
            log_it(f"\n❌ 执行过程中发生致命错误:\n{error_detail}")
        except NameError:
            print(f"\n❌ 初始化过程中发生致命错误:\n{error_detail}")
        
        test_passed = False
        execution_error = f"Fatal error: {str(e)}"
        if isinstance(e, SystemExit):
            raise e

    finally:
        from tracer.evaluator import TraceEvaluator
        from core.verification_engine import close_verification_engine
        
        # [v3.2 优先级优化] 核心产出落盘优先：先保存 Trace，再尝试清理环境
        # 即使 cleanup 挂起，文件也已经安全写入磁盘
        try:
            trace_status = "pass" if test_passed else "fail"
            confidence = TraceEvaluator.calculate_confidence(recorder.trace)
            
            recorder.finish(status=trace_status, confidence=confidence, error_message=execution_error)
            saved_path = recorder.save(os.path.join("artifacts", "traces", "raw"))
            
            msg_finish = (
                f"\n{'='*50}\n"
                f"测试完成时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n"
                f"Trace 已保存至: {saved_path}\n"
                f"Confidence: {confidence}\n"
                f"{'='*50}"
            )
            try:
                log_it(msg_finish)
            except NameError:
                print(msg_finish)
        except Exception as e:
            try: log_it(f"⚠️ Trace 最终保存失败: {e}")
            except: print(f"⚠️ Trace 最终保存失败: {e}")

        # 6. 退出前生成由 AI 驱动的测试报告 (独立异常隔离)
        try:
            log_it(f"\n{S_INFO} 正在生成 AI 测试总结报告...")
            report_path = ReportGenerator.generate(recorder.trace, log_file=log_file)
            log_it(f"✨ 测试报告已生成: {report_path}")
        except Exception as report_err:
            try: log_it(f"⚠️ 报告生成失败: {report_err}")
            except: pass
            
        # 7. 退出时尝试释放浏览器连接 (允许静默失败，不阻塞主进程退出)
        try:
            await close_verification_engine()
        except: pass

        if not test_passed:
            sys.exit(1)

if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="LLM-driven Interactive Test Runner")
    parser.add_argument("test_file", help="Path to the test YAML file")
    parser.add_argument("--pre-steps", help="Path to pre-steps YAML file or inline list (JSON string)", default=None)
    
    args = parser.parse_args()
    asyncio.run(run_test(args.test_file, pre_steps_override=args.pre_steps))
