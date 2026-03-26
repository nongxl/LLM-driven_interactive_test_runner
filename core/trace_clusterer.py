import os
import json
import hashlib
from typing import List, Dict, Any, Optional

class TraceClusterer:
    """
    Trace 聚类系统：用于将多条 Trace 自动去重并提取代表路径。
    """
    
    def __init__(self, threshold: float = 0.7):
        self.threshold = threshold

    def normalize_trace(self, trace: Dict[str, Any]) -> List[str]:
        """
        标准化轨迹：提取 (action_type, target_id/role_name) 序列，剔除重复和无效步骤。
        """
        actions = []
        steps = trace.get("steps", [])
        
        for step in steps:
            sub_actions = step.get("sub_actions", [])
            for sub in sub_actions:
                decision = sub.get("decision", {})
                a_type = decision.get("action")
                
                # 提取目标：优先使用语义定位器，其次是 snapshot_id
                target = "unknown"
                target_obj = decision.get("target")
                if isinstance(target_obj, dict):
                    semantic = target_obj.get("semantic_locator")
                    if semantic:
                        target = f"{semantic.get('role')}_{semantic.get('name')}"
                    else:
                        target = target_obj.get("snapshot_id", "unknown")
                elif isinstance(target_obj, str):
                    target = target_obj
                
                # 标准化动作标识符
                action_id = f"{a_type}:{target}"
                
                # 去重连续重复动作（如多次无效点击）
                if not actions or actions[-1] != action_id:
                    actions.append(action_id)
        
        return actions

    def compute_similarity(self, seq_a: List[str], seq_b: List[str]) -> float:
        """
        使用 LCS (最长公共子序列) 计算两条轨迹的相似度 (0.0 ~ 1.0)。
        """
        m, n = len(seq_a), len(seq_b)
        if m == 0 or n == 0:
            return 0.0
            
        # 动态规划计算 LCS
        dp = [[0] * (n + 1) for _ in range(m + 1)]
        for i in range(1, m + 1):
            for j in range(1, n + 1):
                if seq_a[i-1] == seq_b[j-1]:
                    dp[i][j] = dp[i-1][j-1] + 1
                else:
                    dp[i][j] = max(dp[i-1][j], dp[i][j-1])
        
        lcs_len = dp[m][n]
        # 相似度系数 (Sorensen-Dice 变体)
        return (2.0 * lcs_len) / (m + n)

    def cluster_traces(self, traces: List[Dict[str, Any]]) -> Dict[str, Any]:
        """
        使用 Greedy Clustering 算法对轨迹进行聚类。
        """
        clusters = [] # List[Dict] -> {id, normalized_rep, traces: []}
        
        for trace in traces:
            norm_seq = self.normalize_trace(trace)
            best_match = None
            max_sim = -1.0
            
            # 寻找现有最相似的 Cluster
            for cluster in clusters:
                sim = self.compute_similarity(norm_seq, cluster["normalized_rep"])
                if sim > max_sim:
                    max_sim = sim
                    best_match = cluster
            
            if best_match and max_sim >= self.threshold:
                best_match["traces"].append(trace)
                print(f"DEBUG: Trace {trace.get('metadata', {}).get('trace_id')[:8]} -> Cluster {best_match['cluster_id']} (Sim: {max_sim:.2f})")
            else:
                # 创建新 Cluster
                new_id = f"cluster_{len(clusters) + 1}_{hashlib.md5(str(norm_seq).encode()).hexdigest()[:6]}"
                clusters.append({
                    "cluster_id": new_id,
                    "normalized_rep": norm_seq,
                    "traces": [trace]
                })
                print(f"DEBUG: Created new Cluster {new_id} for Trace {trace.get('metadata', {}).get('trace_id')[:8]}")
        
        # 提取 representative 并清理中间数据
        final_clusters = []
        for cluster in clusters:
            rep = self.select_representative(cluster["traces"])
            final_clusters.append({
                "cluster_id": cluster["cluster_id"],
                "trace_count": len(cluster["traces"]),
                "representative": rep,
                "all_trace_ids": [t.get("metadata", {}).get("trace_id") for t in cluster["traces"]]
            })
            
        return {"clusters": final_clusters}

    def select_representative(self, cluster_traces: List[Dict[str, Any]]) -> Dict[str, Any]:
        """
        挑选代表轨迹：优先级 pass > 短路径 > 高置信度。
        """
        def rank_key(t):
            status = t.get("result", {}).get("status", "fail")
            # 状态分：pass 为 0，fail 为 1 (越小越优)
            status_score = 0 if status == "pass" else 1
            # 长度分：步骤数
            length_score = len(t.get("steps", []))
            # 置信度分：负置信度（越大信度越高，故负值越小越优）
            conf_score = -t.get("result", {}).get("confidence", 0.0)
            return (status_score, length_score, conf_score)
            
        sorted_traces = sorted(cluster_traces, key=rank_key)
        return sorted_traces[0]

    def infer_goal(self, trace: Dict[str, Any]) -> Dict[str, Any]:
        """
        根据轨迹最后一步推断测试目标。
        """
        if not trace.get("steps"):
            return {}
            
        last_step = trace["steps"][-1]
        v_evidence = last_step.get("verification", {}).get("evidence", {})
        
        # 简单推断逻辑
        if "url" in v_evidence:
            return {"type": "url_contains", "value": v_evidence["url"]}
        
        return {"type": "text_present", "value": "SUCCESS"} # 默认兜底

    def export_smoke_tests(self, clusters_data: Dict[str, Any], output_dir: str = "smoke_tests"):
        """
        为每个 Cluster 导出代表性的 Smoke Test 文件 (JSON 和 YAML)。
        """
        import yaml
        os.makedirs(output_dir, exist_ok=True)
        count = 0
        for cluster in clusters_data["clusters"]:
            rep_trace = cluster["representative"]
            # 构造用例格式 (对齐 test_runner YAML 规范)
            smoke_test = {
                "name": f"Smoke Test: {cluster['cluster_id']}",
                "url": rep_trace.get("metadata", {}).get("url", ""),
                "generated_from": rep_trace.get("metadata", {}).get("trace_id"),
                "goal": self.infer_goal(rep_trace),
                "steps": [s.get("instruction") for s in rep_trace.get("steps", [])]
            }
            
            # 导出 JSON (导出原始、完整的 Trace 对象，用于回放)
            json_path = os.path.join(output_dir, f"{cluster['cluster_id']}.json")
            with open(json_path, 'w', encoding='utf-8') as f:
                json.dump(rep_trace, f, indent=2, ensure_ascii=False)
                
            # 导出 YAML (导出指令式的 TestSpec，用于 test_runner 运行)
            yaml_path = os.path.join(output_dir, f"{cluster['cluster_id']}.yaml")
            with open(yaml_path, 'w', encoding='utf-8') as f:
                yaml.dump(smoke_test, f, allow_unicode=True, sort_keys=False)
                
            count += 1
            
        print(f"✅ 已成功导出 {count} 条 Smoke Tests 至 {output_dir}/ (JSON/YAML)")


if __name__ == "__main__":
    # 简单的本地冒烟测试逻辑
    pass
