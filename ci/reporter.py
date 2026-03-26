import json
import os
from datetime import datetime

class TestReporter:
    def __init__(self, report_dir="artifacts/reports"):
        self.report_dir = report_dir
        os.makedirs(self.report_dir, exist_ok=True)
        self.results = []

    def add_result(self, result):
        self.results.append(result)

    def generate_json_report(self, filename="test_report.json"):
        summary = {
            "timestamp": datetime.now().isoformat(),
            "total": len(self.results),
            "passed": len([r for r in self.results if r["status"] == "pass"]),
            "failed": len([r for r in self.results if r["status"] == "fail"]),
            "results": self.results
        }
        
        report_path = os.path.join(self.report_dir, filename)
        with open(report_path, 'w', encoding='utf-8') as f:
            json.dump(summary, f, indent=2, ensure_ascii=False)
        
        return report_path, summary

    def print_summary(self):
        passed = len([r for r in self.results if r["status"] == "pass"])
        failed = len([r for r in self.results if r["status"] == "fail"])
        total = len(self.results)

        print("\n" + "="*50)
        print("📋 自动化测试回归报告汇总")
        print("="*50)
        print(f"总计用例: {total}")
        print(f"✅ 通过: {passed}")
        print(f"❌ 失败: {failed}")
        print("-" * 50)
        
        for r in self.results:
            icon = "✅" if r["status"] == "pass" else "❌"
            name = os.path.basename(r["trace_file"])
            print(f"{icon} {name} ({r['duration']}s)")
            if r["status"] == "fail" and r["error"]:
                print(f"   ┗ 错误: {r['error']}")
        
        print("="*50 + "\n")
