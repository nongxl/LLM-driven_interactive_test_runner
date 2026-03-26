from pydantic import BaseModel, Field
from typing import List, Optional, Literal, Dict, Any, Union

class SnapshotInfo(BaseModel):
    snapshot_hash: str = Field(..., description="Hash of the DOM snapshot")
    page_url: str = Field(..., description="Current page URL")
    title: str = Field(..., description="Current page title")

class SemanticLocator(BaseModel):
    role: Optional[str] = None
    name: Optional[str] = None
    text: Optional[str] = None

class Target(BaseModel):
    snapshot_id: Optional[str] = Field(None, description="e.g., e1, e2")
    semantic_locator: Optional[SemanticLocator] = None

class Decision(BaseModel):
    action: Union[Literal["click", "type", "select", "wait", "navigate", "scroll", "keyboard", "get_text", "screenshot", "assert", "tab", "switch_tab", "wait_load", "goto", "open", "fill", "snapshot"], str]
    target: Optional[Target] = None
    value: Optional[str] = None
    reasoning: str = Field(..., description="LLM decision explanation")
    raw_action: Optional[Dict[str, Any]] = Field(None, description="The raw action JSON from AI / input")
    task_status: Literal["in_progress", "completed"] = "completed"

class Execution(BaseModel):
    status: Literal["success", "failure", "pending"] = "pending"
    duration_ms: Optional[float] = None
    error: Optional[str] = None

class Expected(BaseModel):
    type: str
    value: str

class Verification(BaseModel):
    method: Literal["rule", "ai", "rule+ai", "composite"] = "rule"
    source: Literal["dom", "snapshot", "various"] = "dom"
    result: Literal["pass", "fail", "pending"] = "pending"
    confidence: float = Field(1.0, ge=0.0, le=1.0)
    reason: Optional[str] = None
    evidence: Dict[str, Any] = Field(default_factory=dict)
    snapshot_hash_after: Optional[str] = None

class SubAction(BaseModel):
    snapshot_info: SnapshotInfo
    decision: Decision
    execution: Execution

class Step(BaseModel):
    step_id: int
    instruction: str = Field(..., description="Instruction from test_spec")
    sub_actions: List[SubAction] = Field(default_factory=list)
    expected: Optional[Union[Expected, List[Expected]]] = None
    verification: Optional[Verification] = None

class Metadata(BaseModel):
    trace_id: str
    spec_id: str
    url: str
    start_time: str
    end_time: Optional[str] = None
    duration_ms: Optional[float] = None
    agent_model: str
    runner_version: str

class Result(BaseModel):
    status: Literal["pass", "fail", "pending"] = "pending"
    confidence: float = Field(0.0, ge=0.0, le=1.0)
    error_message: Optional[str] = None

class Trace(BaseModel):
    metadata: Metadata
    result: Result
    steps: List[Step] = Field(default_factory=list)
