# LLM-driven Interactive Test Runner (基于 agent-browser)

本项目旨在实现一个“AI驱动的网页自动化测试执行器”，通过 `agent-browser` 的 snapshot 工作流，结合 LLM（大模型）的决策能力，完成自然语言描述的测试步骤。

## 🏗️ 核心架构 (V3)

- **编排层 (`runner/` & `tracer/`)**: 
    - `test_runner.py`: 驱动新用例执行，包含 AI 辅助决策与单步验证。
    - `exploratory_runner.py`: **V3 核心**，驱动自主探索与全流水线生命周期。
    - `tracer/replay_runner.py`: 驱动历史轨迹的高保真重现与自愈验证。
    - `tracer/recorder.py`: 负责测试全过程的流水数据录制与状态对齐。

- **引擎层 (`core/`)**:
    - `exploration_engine.py`: 负责自主路径选择与页面健康度评估（Health Assessment）。
    - `trace_clusterer.py`: 基于 LCS 算法的轨迹去重与代表性用例提纯引擎。
    - `snapshot_manager.py`: 兼具 ARIA 树抓取与**业务异常主动识别**（System Alert）。
- **执行与验证层**:
    - `action_executor.py`: 指令原子化转换。
    - `verification_engine.py`: 基于 Playwright 的长效 CDP 连结与多维断言系统。
- **资产层 (`artifacts/`)**: 遵循本项目“唯一真理来源”原则，所有运行时产出均需归集于此。

## 📂 资产目录规范 (Mandatory)

为了保持根目录整洁，所有开发者必须遵循以下路径约定：
- **日志**: `artifacts/logs/` (包含探索日志 `log_exploratory_*.log`)
- **轨迹**: `artifacts/traces/raw/` (原始交互序列)
- **冒烟用例**: `artifacts/smoke_tests/` (包含手动与探索自动生成的 JSON/YAML 资产)
- **浏览器配置**: `artifacts/browser_profile*/` (环境隔离的 Profile 目录)

## 🔄 自动化流水线流程

1. **Pre-steps**: 通过交互式 AI（或人工协作）完成登录、弹窗清理等高难度初始化。
2. **Autonomous Exploration**: 引擎根据 `ExplorationEngine` 策略进行无序深度遍历。
3. **Health Assessment**: 每步执行后自动检查页面健康度，探测系统崩溃或权限阻断。
4. **Cleanup**: `finally` 块强制回收 3030 端口与进程。
5. **Clustering & Export**: 自动对比历史轨迹，提取全新路径并更新 Smoke Tests 资产。

## 🤖 Agent 协作指南

### 1. 交互模式操作规范
- **连读模式 (+)**: 在指令末尾添加 `+`，允许连续执行多步（如批量填单）而不触发冗余验证。
- **完成指令**: 输入 `{"task_status": "completed"}` 标志当前步骤结束，移交控制权。

### 3. 主程序入口维护 (`run.py`)
- **唯一入口原则**: 为了防止命令行参数过于复杂，本项目提供 `python run.py` 作为统一交互入口。
- **强制同步**: **后续任何新增的脚本或功能，必须同步在 `run.py` 中增加对应的菜单项与参数引导逻辑。** 严禁发布只有复杂 CLI 参数而无交互引导的功能。

---
*提示：保持 `artifacts/` 作为唯一输出源，任何新增的临时配置文件严禁直接放置于项目根目录。*
