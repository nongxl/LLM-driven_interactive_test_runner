import asyncio
import sys
import os
import json
import time
from datetime import datetime
from typing import Optional

# 强制设置标准输出输出编码为 utf-8，解决 Windows 下的乱码问题
if sys.stdout.encoding != 'utf-8':
    try:
        sys.stdout.reconfigure(encoding='utf-8')
        sys.stderr.reconfigure(encoding='utf-8')
    except (AttributeError, Exception):
        import io
        sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
        sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8')

# 在导入 3rd party 库之前实现环境自引导逻辑
def ensure_venv():
    """
    自引导逻辑：如果当前不在虚拟环境中且项目内存在 .venv，则自动切换。
    """
    if os.getenv("SKIP_BOOTSTRAP") == "1":
        return

    current_exe = sys.executable
    if os.name == 'nt':
        venv_python = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".venv", "Scripts", "python.exe"))
    else:
        venv_python = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".venv", "bin", "python"))

    if os.path.exists(venv_python) and os.path.abspath(current_exe).lower() != venv_python.lower():
        os.environ["SKIP_BOOTSTRAP"] = "1"
        args = [venv_python] + sys.argv
        if os.name == 'nt':
            try:
                sys.exit(subprocess.call(args))
            except Exception as e:
                print(f"❌ 自动环境切换失败: {e}")
        else:
            os.execv(venv_python, args)
        sys.exit(0)

import subprocess
ensure_venv()

# 确保项目根目录在 path 中，以便导入 core, tracer, ai 等模块
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from dotenv import load_dotenv
load_dotenv()

from core.exploration_engine import ExplorationEngine
from core.state_memory import StateMemory
from core.verification_engine import verify, get_playwright_page, close_verification_engine, initialize_verification_engine
from core.snapshot_manager import get_snapshot
from core.action_executor import execute
from tracer.recorder import TraceRecorder
from tracer.evaluator import TraceEvaluator
from core.report_generator import ReportGenerator

async def run_pre_steps(pre_steps: str, recorder: TraceRecorder, log_it):
    """
    在探索开始前执行预设脚本、回放轨迹或进入手工模式。
    """
    import yaml
    from core.action_executor import execute
    from core.snapshot_manager import get_snapshot
    from ai.llm_client import decide_action
    from ai.prompt_builder import init_step_messages, append_snapshot
    from tracer.replay_runner import run_replay
    
    if pre_steps == "__MANUAL__":
        log_it(f"💡 {os.environ.get('BOLD', '')}已开启【手工自由操作】模式。{os.environ.get('RESET', '')}")
        log_it("🛑 请在浏览器中完成操作后，在控制台输入: {\"task_status\": \"completed\"}")
        
        while True:
            snapshot = await get_snapshot(logger=log_it)
            messages = init_step_messages("🛑 [手工前置模式] 请先在浏览器中手动完成操作（如登录、验证码等），完成后回复: {\"task_status\": \"completed\"}")
            append_snapshot(messages, snapshot)
            
            decision = decide_action(messages)
            if decision.get('action') == 'force_exit':
                return
            
            if decision.get('task_status') == 'completed':
                log_it("✅ 手工前置步骤已确认完成。")
                break
            
            # 执行手动输入的动作（如果有）
            await execute(decision)

    elif pre_steps.lower().endswith('.json'):
        log_it(f"📂 正在自动回放前置轨迹 (JSON): {pre_steps}")
        # 调用回放引擎，close_engine=False 保持 Session
        replay_res = await run_replay(pre_steps, strict=True, close_engine=False, logger=log_it)
        if replay_res.get('status') != 'pass':
            log_it(f"❌ 前置轨迹回放失败: {replay_res.get('error')}")
    
    elif os.path.exists(pre_steps):
        log_it(f"📂 正在启动前置语义解析执行 (YAML): {pre_steps}")
        with open(pre_steps, 'r', encoding='utf-8') as f:
            config = yaml.safe_load(f)
        
        steps = config.get('steps', [])
        # 初始化验证引擎
        await initialize_verification_engine()
        
        for i, step_spec in enumerate(steps, 1):
            instruction = step_spec.get('instruction') if isinstance(step_spec, dict) else str(step_spec)
            expected = step_spec.get('expected') if isinstance(step_spec, dict) else None
            log_it(f"\n>>>> [Pre-Step {i}] 正在执行指令: {instruction} <<<<")
            
            step_completed = False
            for retry in range(20): # 提升重试次数
                snapshot = await get_snapshot(logger=log_it)
                page = await get_playwright_page()
                
                # [NEW] 1. 前置校验：如果已经满足预期，则直接完成本步
                if expected and page:
                    v_res = await verify(page, expected, after_snapshot=snapshot, snapshot_id=snapshot.get('snapshot_id'))
                    if v_res['result'] == 'pass':
                        log_it(f" [Pre-Step {i}] ✅ 前置校验通过，指令已自动完成")
                        step_completed = True
                        break
                
                # 2. 调用决策
                messages = init_step_messages(instruction)
                append_snapshot(messages, snapshot)
                decision = decide_action(messages)
                
                # [NEW] 鲁棒性提取：支持 dict 和 list 两种返回格式
                is_list = isinstance(decision, list)
                main_decision = decision[-1] if is_list else decision
                d_status = main_decision.get('task_status') if isinstance(main_decision, dict) else None
                d_action = main_decision.get('action') if isinstance(main_decision, dict) else None

                if d_status == 'completed':
                    log_it(f" [Pre-Step {i}] ✅ AI 标记指令完成")
                    step_completed = True
                    break
                
                if d_action == 'force_exit':
                    return
                    
                log_it(f" [Pre-Step {i}] (Try {retry+1}) 执行动作: {json.dumps(decision, ensure_ascii=False)}")
                await execute(decision)
                
                # 3. 后置校验（动作执行后立即验证）
                # 给页面一点点加载时间
                await asyncio.sleep(1.0)
                if expected:
                    snapshot_after = await get_snapshot(logger=log_it)
                    v_res = await verify(page, expected, after_snapshot=snapshot_after, snapshot_id=snapshot_after.get('snapshot_id'))
                    if v_res['result'] == 'pass':
                        log_it(f" [Pre-Step {i}] ✅ 动作执行后验证通过")
                        step_completed = True
                        break
            
            if not step_completed:
                log_it(f" [Pre-Step {i}] ❌ 执行失败或重试超限。")
    else:
        log_it(f"⚠️ 无法识别前置步骤配置: {pre_steps}")


async def run_exploration(url, max_steps=30, pre_steps=None, interactive=False):
    """
    运行探索性测试过程。
    """
    spec_id = "exploratory"
    recorder = TraceRecorder(spec_id=spec_id, url=url, agent_model="exploratory")
    engine = ExplorationEngine()
    memory = StateMemory()
    
    # 建立文件日志逻辑 (对齐 test_runner)
    time_str = datetime.now().strftime('%m%d_%H%M%S')
    log_filename = f"log_{spec_id}_{time_str}.log"
    log_dir = os.path.join('artifacts', 'logs')
    os.makedirs(log_dir, exist_ok=True)
    log_file_path = os.path.join(log_dir, log_filename)

    from core.utils import cleanup_browser_env, strip_ansi

    def log_it(msg):
        msg_str = str(msg).strip()
        # [Optimization] 增加更鲁棒的全局 DEBUG 过滤开关
        msg_upper = msg_str.upper()
        is_debug = "DEBUG:" in msg_upper or msg_upper.startswith("WAIT ") or msg_upper.startswith("BATCH ")
        show_debug = os.environ.get("TEST_DEBUG") == "1"
        
        # 1. 控制台输出逻辑
        if not is_debug or show_debug:
            print(f"[{datetime.now().strftime('%H:%M:%S')}] {msg_str}", flush=True)
            
        try:
            # 2. 文件保存逻辑
            clean_msg = strip_ansi(msg_str)
            with open(log_file_path, 'a', encoding='utf-8') as f:
                f.write(clean_msg + "\n")
                f.flush()
        except Exception:
            pass
        try:
            clean_msg = strip_ansi(msg_str)
            with open(log_file_path, 'a', encoding='utf-8') as f:
                f.write(f"[{datetime.now().strftime('%H:%M:%S')}] {clean_msg}\n")
        except: pass

    from core.verification_engine import initialize_verification_engine

    # 0. 环境对齐
    os.environ['AGENT_BROWSER_PORT'] = os.getenv('AGENT_BROWSER_PORT', '3030')
    profile_name = os.getenv('AGENT_BROWSER_PROFILE', 'browser_profile')
    
    log_it(f"🧹 正在清理环境 (Profile: {profile_name})...")
    cleanup_browser_env(profile_name=profile_name, logger=log_it)
    
    # 1. 直接触发初始导航
    log_it(f"正在执行初始导航: {url}...")
    await execute({"action": "goto", "target": url})
    log_it("等待 5s 页面加载...")
    await asyncio.sleep(5.0)

    # 2. 执行前置步骤
    if pre_steps:
        await run_pre_steps(pre_steps, recorder, log_it)

    try:
        for step_idx in range(1, max_steps + 1):
            log_it(f"\n--- 步骤 {step_idx} ---")
            
            # 3. 获取快照与 AI 状态自评估
            snapshot = await get_snapshot(logger=log_it)
            if not snapshot or snapshot.get('aria_text') == 'Timeout':
                log_it("⚠️ 无法获取快照，跳过此步")
                continue

            # [V2] AI 智能健康检查
            log_it("🧠 AI 正在评估页面状态...")
            health = await engine.assess_page_health(snapshot)
            h_status = health.get('status', 'unknown')
            log_it(f"📊 状态评估: {h_status} ({health.get('reason', '')})")
            
            # [Fix] 如果健康检查过程中触发了人工退出（如 AI 报错转人工后输入 exit）
            if health.get('action') == 'force_exit':
                log_it("🛑 人工指令：停止探索（在状态评估阶段）。")
                break
                
            # [V3.3] 错误自愈逻辑：如果发现是错误页，尝试逃逸
            if h_status == 'error' or "chrome-error://" in snapshot.get('url', ''):
                page = await get_playwright_page()
                if page:
                    log_it("🛠️  检测到系统级错误或浏览器异常页，启动自愈程序...")
                    # 尝试 1: 返回上一页
                    log_it("  [Recovery] 尝试返回上一页 (Go Back)...")
                    try:
                        await page.go_back(timeout=5000)
                        await asyncio.sleep(2)
                        continue # 跳过本步决策，重新获取快照评估
                    except Exception as ge:
                        log_it(f"  [Recovery] 返回失败: {ge}")
                    
                    # 尝试 2: 如果返回无效，强制重置到起始 URL
                    log_it(f"  [Recovery] 强制重定向至起始页: {url}")
                    await execute({"action": "goto", "target": url})
                    await asyncio.sleep(3)
                    continue 

            # 4. 探索引擎决策
            decision = engine.decide_next_step(snapshot, memory, interactive=interactive)
            if not decision:
                log_it("🏁 没有发现更多可消费的交互元素，停止探索。")
                break
            
            # [Feature] 处理手动模式下的强制退出
            if decision.get('action') == 'force_exit':
                log_it("🛑 各级人工指令：停止探索。")
                break
                
            log_it(f"决定执行: {decision['action']} [{decision.get('ref')}] {decision.get('role')} \"{decision.get('name')}\"")

            # 5. 执行并记录
            instruction = f"探索: {decision.get('role')} {decision.get('name')}"
            recorder.begin_step(instruction=instruction)
            
            start_time = recorder.start_action()
            exec_result = await execute(decision)
            duration_ms = (time.time() - start_time) * 1000
            log_it(f"执行结果: {exec_result}")

            # 6. 自动验证
            log_it("🔍 正在验证操作效果...")
            page = await get_playwright_page()
            if page:
                try:
                    await page.wait_for_load_state("networkidle", timeout=2000)
                except: pass
                
                snapshot_after = await get_snapshot(logger=log_it)
                v_res = await verify(page, {}, snapshot, snapshot_after, snapshot_id=snapshot_after.get('snapshot_id'))
                v_res['health_assessment'] = health
                
                log_it(f"验证: {v_res['result']} - {v_res['reason']}")
                
                # 7. 记录到 Trace 及结束大步骤
                recorder.record_sub_action(
                    pre_snapshot=snapshot,
                    decision_dict=decision,
                    exec_status="success" if not exec_result.startswith("Error") else "failure",
                    exec_error=exec_result if exec_result.startswith("Error") else None,
                    duration_ms=duration_ms
                )
                recorder.finish_step(verification_dict=v_res, post_snapshot_hash=snapshot_after.get('hash', 'unknown'))
            else:
                log_it("⚠️ 无法获取 Page 对象，跳过轨迹记录")

    except Exception as e:
        log_it(f"❌ 探索过程中发生错误: {e}")
        import traceback
        log_it(traceback.format_exc())
    finally:
        # 8. 完成并保存
        confidence = TraceEvaluator.calculate_confidence(recorder.trace)
        recorder.finish(status="pass", confidence=confidence)
        saved_path = recorder.save(os.path.join("artifacts", "traces", "raw"))
        log_it(f"\n✅ 探索完成！Trace 已保存至: {saved_path}")
        log_it(f"📜 本次探索日志已保存至: {log_file_path}")

        # 8.5 [NEW] 生成由 AI 驱动的测试报告
        try:
            log_it(f"\n>>>> 正在生成 AI 测试总结报告...")
            report_path = ReportGenerator.generate(recorder.trace, log_file=log_file_path)
            log_it(f"✨ 测试报告已生成: {report_path}")
        except Exception as report_err:
            log_it(f"⚠️ 报告生成失败: {report_err}")

        # 9. [自动化闭环] 触发聚类分析与冒烟用例提取
        log_it("\n📊 正在自动生成聚类分析报告与 Smoke Tests...")
        try:
            from core.trace_clusterer import TraceClusterer
            raw_dir = os.path.join("artifacts", "traces", "raw")
            output_dir = os.path.join("artifacts", "smoke_tests")
            
            # 加载并聚类

            traces = []
            for f in os.listdir(raw_dir):
                if f.endswith(".json"):
                    with open(os.path.join(raw_dir, f), 'r', encoding='utf-8') as tf:
                        trace_data = json.load(tf)
                        if trace_data:
                            traces.append(trace_data)
            
            if traces:
                clusterer = TraceClusterer(threshold=0.7)
                results = clusterer.cluster_traces(traces)
                clusterer.export_smoke_tests(results, output_dir=output_dir)
                log_it(f"✨ 聚类分析完成！{len(traces)} 条轨迹已提纯。资产已更新至: {output_dir}/")
        except Exception as ce:
            log_it(f"⚠️ 自动化聚类失败: {ce}")

        # 10. 优雅退出：只关闭 Playwright 连接，不杀 OS 进程
        # agent-browser daemon 自行保存 Profile，供下次测试复用登录状态
        log_it(f"🧹 正在关闭 Playwright 连接...")
        await close_verification_engine()


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="探索性测试运行器 V2")
    parser.add_argument("url", help="起始 URL")
    parser.add_argument("steps", type=int, nargs="?", default=30, help="最大步数")
    parser.add_argument("--pre-steps", help="前置 YAML 脚本路径")
    parser.add_argument("-i", "--interactive", action="store_true", help="开启交互式决策模式")
    
    args = parser.parse_args()
    asyncio.run(run_exploration(args.url, args.steps, args.pre_steps, interactive=args.interactive))
