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
            actions_to_check = getattr(step, 'sub_actions', []) if getattr(step, 'sub_actions', []) else [step]
            step_has_failure = False
            for sub in actions_to_check:
                if sub.execution and sub.execution.status != "success":
                    step_has_failure = True
                    break
                    
            if step_has_failure:
                score -= penalty_per_step
            
            # Additional heuristic: Missing post-hash implies verification failed or page crashed
            if not step.verification or not step.verification.snapshot_hash_after:
                score -= (penalty_per_step * 0.2)
                
        return max(0.0, round(score, 2))
