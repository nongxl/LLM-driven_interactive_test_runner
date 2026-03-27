import os
import re
import json
import uuid
from datetime import datetime
from typing import List, Dict, Any, Optional

# Ensure project root is in path
import sys
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from tracer.schema import Trace, Metadata, Result, Step, SubAction, SnapshotInfo, Decision, Execution, Target, SemanticLocator, Verification

class LogToTraceConverter:
    """
    高保真日志轨迹还原引擎 (V3.2)
    能够从包含 [Snapshot ARIA] 标记的日志中还原完整的交互轨迹
    """
    
    def __init__(self, log_path: str):
        self.log_path = log_path
        self.spec_id = os.path.basename(log_path).replace("log_", "").split("_")[0]
        self.steps: List[Step] = []
        self.current_step: Optional[Step] = None
        self.metadata = Metadata(
            trace_id=str(uuid.uuid4()),
            spec_id=self.spec_id,
            url="Recovered from log",
            start_time=datetime.now().isoformat(),
            agent_model="recovered-v3.2",
            runner_version="3.2.0"
        )

    def parse(self) -> Trace:
        if not os.path.exists(self.log_path):
            raise FileNotFoundError(f"Log file not found: {self.log_path}")

        with open(self.log_path, 'r', encoding='utf-8') as f:
            lines = f.readlines()

        i = 0
        last_snapshot_info = None
        
        while i < len(lines):
            line = lines[i].strip()
            
            # 1. 识别大步骤开始
            # >>>> 开始执行步骤 1: 打开监管平台 <<<<
            step_match = re.search(r'>>>> 开始执行步骤 (\d+): (.*?) <<<<', line)
            if step_match:
                step_idx = int(step_match.group(1))
                instruction = step_match.group(2)
                self.current_step = Step(step_id=step_idx, instruction=instruction)
                self.steps.append(self.current_step)
                i += 1
                continue

            # 2. 识别全量快照区块
            if line == "[Snapshot ARIA]":
                aria_content = []
                i += 1
                while i < len(lines) and lines[i].strip() != "[/Snapshot ARIA]":
                    aria_content.append(lines[i])
                    i += 1
                
                full_aria = "".join(aria_content).strip()
                last_snapshot_info = SnapshotInfo(
                    snapshot_hash=f"h_{hash(full_aria) % 1000000}",
                    page_url="unknown (from log)",
                    title="unknown (from log)",
                    aria_text=full_aria # 恢复引擎能感知的 ARIA 树
                )
                i += 1
                continue

            # 3. 识别 AI 决策与语义记录
            # AI 决策: {"action": "click", "target": "e2", "task_status": "completed"}
            if "AI 决策:" in line and self.current_step:
                try:
                    decision_json_str = line.split("AI 决策:", 1)[1].strip()
                    decision_dict = json.loads(decision_json_str)
                    
                    # 尝试查找接下来的语义属性记录
                    # [Trace] 捕获语义属性: role='button', name='图标: user 登录'
                    semantic = None
                    next_idx = i + 1
                    # 往后看 5 行查找语义记录和结果
                    exec_status = "success"
                    exec_error = None
                    duration = 1000.0
                    
                    for k in range(1, 6):
                        if i + k >= len(lines): break
                        look_line = lines[i+k].strip()
                        
                        # 语义定位器匹配
                        sem_match = re.search(r"role='([^']*)', name='([^']*)'", look_line)
                        if sem_match:
                            semantic = SemanticLocator(role=sem_match.group(1), name=sem_match.group(2))
                        
                        # 执行结果匹配
                        if "执行结果: [OK]" in look_line:
                            exec_status = "success"
                        elif "执行结果: [" in look_line and "]" in look_line:
                            exec_status = "failure"
                            exec_error = look_line.split("执行结果:", 1)[1].strip()

                    # 构建决策对象
                    target = None
                    target_val = decision_dict.get("target")
                    if target_val:
                        target = Target(
                            snapshot_id=target_val if isinstance(target_val, str) else None,
                            semantic_locator=semantic
                        )

                    decision_obj = Decision(
                        action=decision_dict.get("action", "click"),
                        target=target,
                        value=decision_dict.get("value"),
                        reasoning=decision_dict.get("reasoning", "Recovered from log"),
                        task_status=decision_dict.get("task_status", "completed")
                    )

                    execution_obj = Execution(
                        status=exec_status,
                        duration_ms=duration,
                        error=exec_error
                    )

                    sub_action = SubAction(
                        snapshot_info=last_snapshot_info if last_snapshot_info else SnapshotInfo(snapshot_hash="empty", page_url="", title=""),
                        decision=decision_obj,
                        execution=execution_obj
                    )
                    self.current_step.sub_actions.append(sub_action)
                except Exception as e:
                    print(f"⚠️ 解析决策行失败 (Line {i+1}): {e}")

            # 4. 识别验证结果
            # 验证结果: pass (composite) - ...
            if "验证结果:" in line and self.current_step:
                v_line = line.split("验证结果:", 1)[1].strip()
                status = "pass" if v_line.startswith("pass") else "fail"
                self.current_step.verification = Verification(
                    result=status,
                    reason=v_line,
                    method="log_recovery"
                )

            i += 1

        # 构建最终 Trace
        trace_result = Result(
            status="pass" if all(s.verification and s.verification.result == "pass" for s in self.steps if s.verification) else "fail",
            confidence=0.9,
            error_message="Recovered from log"
        )
        
        return Trace(metadata=self.metadata, steps=self.steps, result=trace_result)

    def save_trace(self, output_dir: str = "artifacts/traces/raw") -> str:
        trace = self.parse()
        os.makedirs(output_dir, exist_ok=True)
        
        timestamp = datetime.now().strftime('%m%d_%H%M%S')
        filename = f"trace_{self.spec_id}_{timestamp}_recovered.json"
        path = os.path.join(output_dir, filename)
        
        with open(path, 'w', encoding='utf-8') as f:
            f.write(trace.model_dump_json(indent=2))
        
        return path

if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Log To Trace Recovery Tool")
    parser.add_argument("log_file", help="Path to the log file")
    args = parser.parse_args()
    
    converter = LogToTraceConverter(args.log_file)
    saved_path = converter.save_trace()
    print(f"✅ 轨迹恢复成功！文件已导出: {saved_path}")
