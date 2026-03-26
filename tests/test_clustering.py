import json
import os
import sys

# Ensure project root is in path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from core.trace_clusterer import TraceClusterer

def create_mock_trace(trace_id, actions_desc, status="pass", confidence=0.9):
    """
    构造简化的模拟 Trace 数据（仅包含核心结构）。
    """
    steps = []
    for i, act in enumerate(actions_desc):
        steps.append({
            "step_id": i + 1,
            "instruction": f"模拟步骤 {i+1}",
            "sub_actions": [
                {
                    "decision": {
                        "action": act["type"],
                        "target": act["target"]
                    }
                }
            ],
            "verification": {
                "evidence": {"url": f"http://site.com/{act['target']}" if i == len(actions_desc)-1 else None}
            }
        })
    
    return {
        "metadata": {"trace_id": trace_id},
        "result": {"status": status, "confidence": confidence},
        "steps": steps
    }

def main():
    clusterer = TraceClusterer(threshold=0.6) # 使用较低阈值以适应简略模拟
    
    # 构造模拟数据
    # Trace 1: 登录流程 A
    t1 = create_mock_trace("T1_LOGIN_NORMAL", [
        {"type": "type", "target": "username"},
        {"type": "type", "target": "password"},
        {"type": "click", "target": "login_btn"}
    ])
    
    # Trace 2: 登录流程 A 的变体 (多了一次点击噪声)
    t2 = create_mock_trace("T2_LOGIN_REDUNDANT", [
        {"type": "type", "target": "username"},
        {"type": "type", "target": "password"},
        {"type": "click", "target": "login_btn"},
        {"type": "click", "target": "login_btn"} # 重复
    ])
    
    # Trace 3: 完全不同的流程 B (进入子系统)
    t3 = create_mock_trace("T3_SUBSYSTEM", [
        {"type": "click", "target": "subsystem_card"},
        {"type": "click", "target": "back_btn"}
    ])
    
    traces = [t1, t2, t3]
    
    print("\n--- 正在执行 Trace 聚类分析 ---")
    results = clusterer.cluster_traces(traces)
    
    print("\n--- 聚类结果汇报 ---")
    for cluster in results["clusters"]:
        print(f"Cluster ID: {cluster['cluster_id']}")
        print(f"  - 包含轨迹数: {cluster['trace_count']}")
        print(f"  - 代表轨迹 ID: {cluster['representative']['metadata']['trace_id']}")
        print(f"  - 原始轨迹 ID 列表: {cluster['all_trace_ids']}")
    
    # 导出 Smoke Tests
    print("\n--- 正在导出 Smoke Tests ---")
    clusterer.export_smoke_tests(results, output_dir="artifacts/smoke_tests")

if __name__ == "__main__":
    main()
