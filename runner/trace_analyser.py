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
    print(f"🔍 正在从 {directory} 加载 {len(files)} 个轨迹文件...")
    
    for filename in files:
        try:
            with open(os.path.join(directory, filename), 'r', encoding='utf-8') as f:
                data = json.load(f)
                # 简单校验是否为标准的 Trace 格式
                if "metadata" in data and "steps" in data:
                    traces.append(data)
        except Exception as e:
            print(f"⚠️ 无法加载文件 {filename}: {e}")
            
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
        print("🏁 没有可供分析的轨迹数据。")
        return

    # 2. 初始化聚类器
    clusterer = TraceClusterer(threshold=args.threshold)
    
    # 3. 执行聚类
    print("\n--- 正在执行聚类分析 ---")
    results = clusterer.cluster_traces(traces)
    
    # 4. 打印统计信息
    print("\n" + "="*40)
    print(f"📊 聚类汇总报告")
    print("-" * 40)
    print(f"输入总轨迹数: {len(traces)}")
    print(f"聚类后的独立路径数: {len(results['clusters'])}")
    print(f"压缩比: {(1.0 - len(results['clusters'])/len(traces))*100:.1f}%")
    print("=" * 40)
    
    for cluster in results["clusters"]:
        print(f"📍 Cluster: {cluster['cluster_id']}")
        print(f"   - 包含轨迹: {len(cluster['all_trace_ids'])} 条")
        print(f"   - 代表 Trace ID: {cluster['representative'].get('metadata', {}).get('trace_id')}")
    
    # 5. 导出结果
    print("\n--- 正在导出 Smoke Tests ---")
    clusterer.export_smoke_tests(results, output_dir=args.output)
    print(f"✅ 完成！核心测试路径已保存至: {args.output}/")

if __name__ == "__main__":
    main()
