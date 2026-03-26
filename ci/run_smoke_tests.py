import asyncio
import os
import sys
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
    args = parser.parse_args()

    # 1. 初始化报告器
    reporter = TestReporter()
    
    # 2. 找到所有测试用例
    test_files = glob.glob(os.path.join(args.dir, "*.json"))
    if not test_files:
        print(f"❌ 错误: 在 {args.dir} 中未找到任何 JSON 测试用例。")
        sys.exit(1)

    print(f"🔍 发现 {len(test_files)} 个冒烟测试用例...\n")

    # 3. 顺序执行回放
    for test_file in test_files:
        print(f"▶ 正在运行: {os.path.basename(test_file)}")
        result = await run_replay(test_file, strict=False) # 在 CI 层面我们可以继续跑完所有用例
        reporter.add_result(result)
        
        if args.strict and result["status"] == "fail":
            print(f"🛑 严格模式: 由于 {test_file} 失败，停止后续测试。")
            break

    # 4. 生成报告
    report_path, summary = reporter.generate_json_report()
    reporter.print_summary()
    
    print(f"详细报告已保存至: {report_path}")

    # 5. 根据结果返回 exit code
    if summary["failed"] > 0:
        sys.exit(1)
    else:
        sys.exit(0)

if __name__ == "__main__":
    asyncio.run(main())
