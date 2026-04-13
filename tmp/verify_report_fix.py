import os
import json
from core.report_generator import ReportGenerator
from tracer.schema import Trace

def verify():
    # 使用用户提到的原始轨迹文件
    trace_path = r"artifacts\traces\raw\trace_exploratory_0413_163533_pass.json"
    if not os.path.exists(trace_path):
        print(f"Error: Trace file not found at {trace_path}")
        return

    print(f"Loading trace: {trace_path}")
    with open(trace_path, 'r', encoding='utf-8') as f:
        trace_data = json.load(f)
    
    # 转换为 Trace 对象
    trace = Trace(**trace_data)
    
    print(f"Trace loaded successfully. Steps: {len(trace.steps)}")
    
    # 生成新报告 (不传入 log_file 以免混合日志干扰)
    report_path = ReportGenerator.generate(trace, logger=print)
    
    print(f"\n✅ New report generated at: {report_path}")
    print("Please verify that the SQL error and '数据库操作失败' are now listed in the '关键发现' section.")

if __name__ == "__main__":
    verify()
