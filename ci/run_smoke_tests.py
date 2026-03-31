import sys
import io

# 兼容 Windows 终端 Emoji 输出
if sys.platform == "win32" and isinstance(sys.stdout, io.TextIOWrapper):
    sys.stdout.reconfigure(encoding='utf-8')

import asyncio
import os
import argparse
import glob

# 把项目根目录加到 sys.path
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from tracer.replay_runner import run_replay
from ci.reporter import TestReporter

async def main():
    parser = argparse.ArgumentParser(description="Run all smoke tests and generate report.")
    parser.add_argument("--dir", type=str, default="artifacts/smoke_tests", help="Directory containing smoke test JSON files")
    parser.add_argument("--strict", action="store_true", help="Stop suite on first test failure")
    parser.add_argument("--pre-steps", type=str, help="Global pre-steps for the whole suite (__MANUAL__ or path to .json/.yaml)")
    args = parser.parse_args()

    # 1. 设置回放专用的环境变量（隔离 3031 端口）
    os.environ["AGENT_BROWSER_PORT"] = "3031"
    os.environ["AGENT_BROWSER_PROFILE"] = "browser_profile_replay"
    
    # 初始化报告器
    reporter = TestReporter()
    
    from core.utils import cleanup_browser_env, S_INFO, S_OK, S_ERR
    from core.verification_engine import initialize_verification_engine, close_verification_engine
    
    # 2. 找到所有测试用例
    test_files = glob.glob(os.path.join(args.dir, "*.json"))
    if not test_files:
        print(f"❌ 警告: 在 {args.dir} 中未找到任何 JSON 轨迹。")
        print(f"💡 提示: 请先在 run.py 中运行「4. 轨迹聚类与分析」以从录制轨迹中提纯出金牌回归用例。")
        sys.exit(0)

    print(f"🔍 发现 {len(test_files)} 个冒烟测试用例...")
    
    # 环境清理与初始化
    cleanup_browser_env(profile_name="browser_profile_replay")
    await initialize_verification_engine()

    try:
        # 3. 执行全局前置步骤 (如果指定)
        if args.pre_steps:
            print(f"\n{S_INFO} 正在执行全局前置步骤: {args.pre_steps}")
            if args.pre_steps == "__MANUAL__":
                from ai.llm_client import decide_action
                from core.snapshot_manager import get_snapshot
                from ai.prompt_builder import init_step_messages, append_snapshot
                from core.action_executor import execute
                print(f"💡 已开启【手工自由操作】模式。请在浏览器中完成操作后，在控制台输入: {{\"task_status\": \"completed\"}}")
                while True:
                    snapshot = await get_snapshot()
                    messages = init_step_messages("🛑 [CI 全局手工前置] 请完成必要操作后回复 completed。")
                    append_snapshot(messages, snapshot)
                    decision = decide_action(messages)
                    if decision.get('task_status') == 'completed': break
                    await execute(decision)
            elif args.pre_steps.lower().endswith('.json'):
                # 调用回放引擎，保持 Session
                await run_replay(args.pre_steps, strict=True, close_engine=False)
            else:
                print(f"⚠️ 批量测试目前暂不支持 YAML 格式的全局前置，请优先使用 JSON 轨迹。")

        # 4. 顺序执行回放
        for test_file in test_files:
            print(f"\n▶ 正在运行: {os.path.basename(test_file)}")
            # [Optimization] 使用 close_engine=False 保持 Session 连贯性
            result = await run_replay(test_file, strict=False, close_engine=False)
            reporter.add_result(result)
            
            if args.strict and result["status"] == "fail":
                print(f"🛑 严格模式: 由于 {test_file} 失败，停止后续测试。")
                break
    finally:
        # 统一清理
        await close_verification_engine()

    # 5. 生成报告
    report_path, summary = reporter.generate_json_report()
    reporter.print_summary()
    
    print(f"详细报告已保存至: {report_path}")

    # 6. 根据结果返回 exit code
    if summary["failed"] > 0:
        sys.exit(1)
    else:
        sys.exit(0)

if __name__ == "__main__":
    asyncio.run(main())
