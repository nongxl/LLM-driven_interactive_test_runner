from .schema import Trace

class TraceEvaluator:
    @staticmethod
    def calculate_confidence(trace: Trace) -> float:
        """
        Calculates a simple confidence score (0-1) for a completed trace.
        - Execution success for each step
        - Hash integrity
        """
        if not trace.steps:
            return 0.0
            
        total_steps = len(trace.steps)
        score = 1.0
        penalty_per_step = 1.0 / total_steps
        
        for step in trace.steps:
            # 安全获取 sub_actions
            sub_actions = getattr(step, 'sub_actions', [])
            step_has_failure = False
            
            if not sub_actions:
                # 如果没有子动作，且验证没通过，视为失败
                if step.verification and step.verification.result != "pass":
                    step_has_failure = True
            else:
                for sub in sub_actions:
                    # 只有 SubAction 对象才有 execution 属性
                    if hasattr(sub, 'execution') and sub.execution and sub.execution.status != "success":
                        step_has_failure = True
                        break
                    
            if step_has_failure:
                score -= penalty_per_step
            
            # Additional heuristic: Missing post-hash implies verification failed or page crashed
            if not step.verification or not step.verification.snapshot_hash_after:
                score -= (penalty_per_step * 0.2)
                
        return max(0.0, round(score, 2))
