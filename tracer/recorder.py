import os
import time
import uuid
from datetime import datetime, timezone
from typing import Optional, Dict, Any

from .schema import Trace, Metadata, TraceResult, Step, SubAction, SnapshotInfo, Decision, Execution, Target, SemanticLocator, Verification, Expected

class TraceRecorder:
    def __init__(self, spec_id: str, url: str, agent_model: str = "unknown", runner_version: str = "1.0.0"):
        self.spec_id = spec_id
        self.start_timestamp = time.time()
        
        metadata = Metadata(
            trace_id=str(uuid.uuid4()),
            spec_id=spec_id,
            url=url,
            start_time=datetime.now(timezone.utc).isoformat(),
            agent_model=agent_model,
            runner_version=runner_version
        )
        self.trace = Trace(metadata=metadata, result=TraceResult())
        self.current_step: Optional[Step] = None
        
    def begin_step(self, instruction: str, expected_dict: Optional[Dict[str, Any]] = None):
        """记录开始一个大步骤"""
        expected = None
        if expected_dict:
            if isinstance(expected_dict, list):
                expected = [Expected(**item) for item in expected_dict]
            else:
                expected = Expected(**expected_dict)
                
        self.current_step = Step(
            step_id=len(self.trace.steps) + 1,
            instruction=instruction,
            expected=expected
        )
        self.trace.steps.append(self.current_step)
        
    def start_action(self) -> float:
        """Returns the start time of the action for duration calculation."""
        return time.time()
        
    def record_sub_action(self, 
                          pre_snapshot: Dict[str, Any], 
                          decision_dict: Dict[str, Any], 
                          exec_status: str, 
                          exec_error: Optional[str], 
                          duration_ms: float):
        """记录完成一个子动作"""
        if not self.current_step:
            return
            
        snapshot_info = SnapshotInfo(
            snapshot_hash=pre_snapshot.get('hash', ''),
            page_url=pre_snapshot.get('url', ''),
            title=pre_snapshot.get('title', '')
        )
        
        # Parse decision safely
        target_val = decision_dict.get("target")
        target = None
        if isinstance(target_val, dict):
            semantic = target_val.get("semantic_locator")
            semantic_locator = SemanticLocator(**semantic) if semantic else None
            target = Target(
                snapshot_id=target_val.get("snapshot_id"),
                semantic_locator=semantic_locator
            )
        elif isinstance(target_val, str):
            # 处理字符串目标 (如 "e1" 或 URL)
            if target_val.startswith('e') and any(c.isdigit() for c in target_val):
                target = Target(snapshot_id=target_val)
            else:
                # 如果是 URL 且 value 为空，将其填入 value 以保证 schema 兼容
                if not decision_dict.get("value"):
                    decision_dict["value"] = target_val
            
        action_name = decision_dict.get("action", "click")
        if action_name == "goto":
            action_name = "navigate"
            
        decision = Decision(
            action=action_name, # type: ignore
            target=target,
            value=decision_dict.get("value"),
            reasoning=decision_dict.get("reasoning", "No reasoning provided"),
            raw_action=decision_dict.get("raw_action"),
            task_status=decision_dict.get("task_status", "completed")
        )
        
        execution = Execution(
            status=exec_status, # type: ignore
            duration_ms=duration_ms,
            error=exec_error
        )
        
        sub_action = SubAction(
            snapshot_info=snapshot_info,
            decision=decision,
            execution=execution
        )
        
        self.current_step.sub_actions.append(sub_action)

    def finish_step(self, verification_dict: Optional[Dict[str, Any]], post_snapshot_hash: Optional[str]):
        """结束当前大步骤，记录最终验证结果"""
        if not self.current_step:
            return
            
        if verification_dict:
            verification = Verification(**verification_dict)
            verification.snapshot_hash_after = post_snapshot_hash
        else:
            verification = Verification(snapshot_hash_after=post_snapshot_hash)
            
        self.current_step.verification = verification
        self.current_step = None
        
        # [v3.2 优化] 步骤完成后自动开启增量持久化，防止崩溃丢数据
        try:
            self.save(is_partial=True)
        except:
            pass
        
    def finish(self, status: str, confidence: float, error_message: Optional[str] = None):
        """完成 Trace 的记录，计算整体验证分数"""
        end_timestamp = time.time()
        self.trace.metadata.end_time = datetime.now(timezone.utc).isoformat()
        self.trace.metadata.duration_ms = (end_timestamp - self.start_timestamp) * 1000
        
        self.trace.result.status = status # type: ignore
        self.trace.result.confidence = confidence
        self.trace.result.error_message = error_message
        
    def save(self, directory: str = "artifacts/traces/raw", is_partial: bool = False) -> str:
        """将 JSON 数据写入文件"""
        try:
            os.makedirs(directory, exist_ok=True)
            time_str = datetime.fromtimestamp(self.start_timestamp).strftime('%m%d_%H%M%S')
            
            # 使用简短的状态标识：success -> pass, failure -> fail
            status = self.trace.result.status or "fail"
            status_suffix = "pass" if status == "pass" else "fail"
            
            # 增量快照采用特殊后缀
            filename = f"trace_{self.spec_id}_{time_str}_{status_suffix}"
            if is_partial:
                filename += "_partial"
            filename += ".json"
            
            filepath = os.path.join(directory, filename)
            
            # 如果是最终保存，且存在之前的任何 partial 文件，尝试清理它们
            if not is_partial:
                import glob
                # 无论之前的状态是 pass/fail/pending，清理所有匹配 spec_id 和 time_str 的增量文件
                partial_pattern = os.path.join(directory, f"trace_{self.spec_id}_{time_str}_*_partial.json")
                for p_f in glob.glob(partial_pattern):
                    try: os.remove(p_f)
                    except: pass

            with open(filepath, 'w', encoding='utf-8') as f:
                f.write(self.trace.model_dump_json(indent=2))
            return filepath
        except Exception as e:
            # 增量保存失败不抛错，避免因磁盘/权限问题导致测试中断
            if not is_partial: raise e
            return ""
