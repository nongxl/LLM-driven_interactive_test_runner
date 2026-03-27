import asyncio
import sys
import os
import json
import time
from datetime import datetime
from typing import Optional

# Ensure project root is in path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from core.exploration_engine import ExplorationEngine
from core.state_memory import StateMemory
from core.verification_engine import verify, get_playwright_page, close_verification_engine
from core.snapshot_manager import get_snapshot
from core.action_executor import execute
from tracer.recorder import TraceRecorder
from tracer.evaluator import TraceEvaluator

async def run_pre_steps(yaml_path: str, recorder: TraceRecorder, log_it):
    """
    在探索开始前执行一段预设的 YAML 脚本。
    需要真实抓取快照并调用 AI 进行指令解析。
    """
    import yaml
    from core.action_executor import execute
    from core.snapshot_manager import get_snapshot
    from ai.llm_client import decide_action
    from ai.prompt_builder import init_step_messages, append_snapshot
    
    if not os.path.exists(yaml_path):
        log_it(f"⚠️ 前置脚本不存在: {yaml_path}")
        return
        
    log_it(f"📂 正在启动前置语义解析执行: {yaml_path}")
    with open(yaml_path, 'r', encoding='utf-8') as f:
        config = yaml.safe_load(f)
    
    steps = config.get('steps', [])
    for i, step_spec in enumerate(steps, 1):
        instruction = step_spec.get('instruction') if isinstance(step_spec, dict) else str(step_spec)
        log_it(f" [Pre-Step {i}] 正在分析指令: {instruction}")
        
        # 核心修复：为前置脚本的每一步也引入 AI 闭环
        for retry in range(5): # 每个指令最多重试 5 次 AI 决策
            snapshot = await get_snapshot(logger=log_it)
            messages = init_step_messages(instruction)
            append_snapshot(messages, snapshot)
            
            # 调用 AI 决策
            decision = decide_action(messages)
            if decision.get('task_status') == 'completed':
                log_it(f" [Pre-Step {i}] ✅ 指令已标记完成")
                break
                
            log_it(f" [Pre-Step {i}] (Try {retry+1}) 执行 AI 动作: {json.dumps(decision, ensure_ascii=False)}")
            await execute(decision)
            await asyncio.sleep(2.0)


async def run_exploration(url, max_steps=30, pre_steps=None):
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
        msg_str = str(msg)
        print(f"[{datetime.now().strftime('%H:%M:%S')}] {msg_str}", flush=True)
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
            log_it(f"📊 状态评估: {health.get('status', 'unknown')} ({health.get('reason', '')})")
            
            # 4. 探索引擎决策
            decision = engine.decide_next_step(snapshot, memory)
            if not decision:
                log_it("🏁 没有发现更多可消费的交互元素，停止探索。")
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
                v_res = await verify(page, {}, snapshot, snapshot_after)
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
                        traces.append(json.load(tf))
            
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
    
    args = parser.parse_args()
    asyncio.run(run_exploration(args.url, args.steps, args.pre_steps))

