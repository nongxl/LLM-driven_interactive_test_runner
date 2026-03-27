# LLM-driven Interactive Test Runner (基于 agent-browser)

本项目旨在实现一个“AI驱动的网页自动化测试执行器”，通过 `agent-browser` 的 snapshot 工作流，结合 LLM（大模型）的决策能力，完成自然语言描述的测试步骤。

## 🏗️ 核心架构 (V3)

- **编排层 (`runner/` & `tracer/`)**: 
    - `test_runner.py`: 驱动新用例执行，包含 AI 辅助决策与单步验证。
    - `exploratory_runner.py`: **V3 核心**，驱动自主探索与全流水线生命周期。
    - `tracer/replay_runner.py`: 驱动历史轨迹的高保真重现与自愈验证。
    - `tracer/recorder.py`: 负责测试全过程的流水数据录制与状态对齐。
    - `tracer/trace_recovery.py`: **V3.2 新增**，离线轨迹还原引擎。支持从日志文件中提取全量快照，高保真生成对应的 JSON 轨迹。
    - `core/report_generator.py`: **V3.1 新增**，测试结束后自动调用 LLM 生成业务总结报告。

- **引擎层 (`core/`)**:
    - `exploration_engine.py`: 负责自主路径选择与页面健康度评估（Health Assessment）。
    - `trace_clusterer.py`: 基于 LCS 算法的轨迹去重与代表性用例提纯引擎。
    - **SnapshotManager**: 兼具 ARIA 树抓取与**业务异常主动识别**。在 V3.2 中，它配合 `test_runner.py` 将快照全量持久化于日志中，为轨迹恢复提供底层数据支撑。
采用**增量扫描（Incremental Scan）**策略：只在 URL 变化后的首次快照执行三重扫描（Toast/浮窗/关键词），相同 URL 下重复快照直接跳过，显著降低 LLM 决策延迟。**v1.9 起改用 `batch` 命令**，将 `wait networkidle + snapshot` 合并为**单次 IPC 调用**，消除多次进程握手开销。
- **执行与验证层**:
    - `action_executor.py`: 指令原子化转换。
    - `verification_engine.py`: 基于 Playwright 的长效 CDP 连结与多维断言系统。
- **资产层 (`artifacts/`)**: 遵循本项目“唯一真理来源”原则，所有运行时产出均需归集于此。

## 📂 资产目录规范 (Mandatory)

为了保持根目录整洁，所有开发者必须遵循以下路径约定：
- **日志**: `artifacts/logs/` (包含探索日志 `log_exploratory_*.log`)
- **报告**: `artifacts/reports/` (包含 AI 总结报告 `report_*.md` 及截图)
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

## ⚡ 性能设计原则 (v1.8+)

为保证框架执行速度接近 Antigravity 等工具的水平，所有开发者和 AI Agent 在修改核心路径时必须遵守以下原则：

1. **禁止固定延迟 (No Fixed Sleep)**：主执行循环中严禁使用 `await asyncio.sleep(N)` 作为稳定等待手段。应使用 `page.wait_for_load_state('networkidle', timeout=...)` 替代。
2. **增量扫描优先 (Incremental Scan First)**：任何检测逻辑（业务报错、元素状态）应先判断是否需要重复扫描，相同页面状态下应跳过，避免每次快照都触发高代价 `evaluate()`。
3. **日志不阻塞 (Non-blocking Log)**：日志写入使用 `f.flush()` 即可，严禁引入 `os.fsync()` 到热路径（高频调用的函数）中。
4. **合并 Round-trip (Batch Evaluate)**：与浏览器之间的 `evaluate()` 调用应尽量合并，避免同一次快照周期内多次往返。

## 🛡️ 弹窗自愈逻辑 (Popup Self-Healing)

为了保证测试流的连续性，V3.1 引入了启发式自愈机制：
1. **自动识别**：当 `SnapshotManager` 探测到页面存在 `global_alerts` 时触发。
2. **特征匹配**：框架自动在 ARIA 树中寻找符合 `Close`, `Cancel`, `确定`, `我知道了` 等特征的按钮。
3. **静默修复**：在 AI 决策前自动点击上述按钮并等待环境稳定。
4. **留证**：所有被触发自愈的瞬间都会自动截屏存入 `artifacts/reports/screenshots`。
