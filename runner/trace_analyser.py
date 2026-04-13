import os
import sys
import json
import argparse
from typing import List

# 兼容 Windows 终端 Emoji 输出 (必须在任何 print 之前)
if sys.platform == "win32":
    import sys
    import io
    if isinstance(sys.stdout, io.TextIOWrapper):
        sys.stdout.reconfigure(encoding='utf-8')

# Ensure project root is in path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

import os
from datetime import datetime

# 日志控制逻辑
def log_it(msg, is_debug=False):
    msg_str = str(msg).strip()
    if is_debug:
        if os.environ.get("TEST_DEBUG") != "1":
            return
        prefix = f"[{datetime.now().strftime('%H:%M:%S')}] DEBUG: "
    else:
        prefix = f"[{datetime.now().strftime('%H:%M:%S')}] "
    
    print(f"{prefix}{msg_str}", flush=True)

from core.trace_clusterer import TraceClusterer

def load_traces(directory: str) -> List[dict]:
    """
    从指定目录加载所有 JSON 轨迹文件。
    """
    traces = []
    if not os.path.exists(directory):
        print(f"❌ 目录不存在: {directory}")
        return []
    
    files = [f for f in os.listdir(directory) if f.endswith(".json")]
    log_it(f"🔍 正在从 {directory} 加载 {len(files)} 个轨迹文件...")
    
    for filename in files:
        try:
            with open(os.path.join(directory, filename), 'r', encoding='utf-8') as f:
                data = json.load(f)
                # 简单校验是否为标准的 Trace 格式
                if "metadata" in data and "steps" in data:
                    traces.append(data)
        except Exception as e:
            log_it(f"⚠️ 无法加载文件 {filename}: {e}", is_debug=True)
            
    return traces

def main():
    parser = argparse.ArgumentParser(description="Trace 分析与聚类工具")
    parser.add_argument("--dir", default="artifacts/traces/raw", help="Trace 文件存放目录")
    parser.add_argument("--output", default="artifacts/smoke_tests", help="Smoke Tests 输出目录")
    parser.add_argument("--threshold", type=float, default=0.7, help="相似度阈值 (0.0-1.0)")
    args = parser.parse_args()

    # 1. 加载数据
    traces = load_traces(args.dir)
    if not traces:
        log_it("🏁 没有可供分析的轨迹数据。")
        return

    # 2. 初始化聚类器
    clusterer = TraceClusterer(threshold=args.threshold, logger=log_it)
    
    # 3. 执行聚类
    log_it("\n--- 正在执行聚类分析 ---")
    results = clusterer.cluster_traces(traces)
    
    # 4. 打印统计信息
    log_it("\n" + "="*40)
    log_it(f"📊 聚类汇总报告")
    log_it("-" * 40)
    log_it(f"输入总轨迹数: {len(traces)}")
    log_it(f"聚类后的独立路径数: {len(results['clusters'])}")
    log_it(f"压缩比: {(1.0 - len(results['clusters'])/len(traces))*100:.1f}%")
    log_it("=" * 40)
    
    for cluster in results["clusters"]:
        log_it(f"📍 Cluster: {cluster['cluster_id']}")
        log_it(f"   - 包含轨迹: {len(cluster['all_trace_ids'])} 条")
        log_it(f"   - 代表 Trace ID: {cluster['representative'].get('metadata', {}).get('trace_id')}")
    
    # 5. 导出结果
    log_it("\n--- 正在导出 Smoke Tests ---")
    clusterer.export_smoke_tests(results, output_dir=args.output)
    log_it(f"✅ 完成！核心测试路径已保存至: {args.output}/")

if __name__ == "__main__":
    main()
