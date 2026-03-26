# LLM-driven Interactive Test Runner

An intelligent, interactive web automation testing framework powered by **agent-browser** and **Large Language Models (LLMs)**.

## 🚀 Key Features

- **Dual Data Stream Architecture**: 
  - **Decision Flow**: Uses `agent-browser` ARIA snapshots for cost-effective AI decision making.
  - **Verification Flow**: Uses Playwright DOM/Page state for high-reliability assertions.
- **Automated Regression Testing (CI)**: 
  - **Trace Replay**: High-fidelity replay of recorded user journeys with automated state validation.
  - **CI Integration**: Returns non-zero exit codes on failure and generates JSON/Markdown reports for pipeline visibility.
- **Exploratory Testing System**:
  - **Autonomous Discovery**: Uses a `Coverage First` strategy to traverse UI branches without a pre-defined script.
  - **State Deduplication**: `StateMemory` prevents redundant actions by fingerprinting ARIA tree states.
- **AI-Powered Verification**: A sophisticated `Verification Engine` that combines rule-based DOM checks with AI-based snapshot analysis as a fallback.

<details>
<summary><b>🇨🇳 点击展开中文特性说明 (Click to expand Chinese Features)</b></summary>

### 核心特性 (中文版)
- **双流数据架构**：决策流使用 ARIA 快照（省 Token），验证流使用原生 Playwright DOM（高可靠）。
- **自动化回归测试**：支持高保真录制与回放，具备自动状态校验，完美集成 CI/CD。
- **自主探索测试**：
  - **自动发现**：无需脚本，采用“覆盖率优先”算法自动遍历 UI 分支。
  - **状态去重**：通过 `StateMemory` 对 ARIA 树进行指纹识别，防止死循环。
- **AI 辅助验证**：结合规则校验（URL、文本、元素）与 AI 视觉分析，确保测试结果真实有效。
- **自愈定位器**：优先使用 `ref=eXX` 定位，若目标漂移则触发 `Auto-Healing` 自动修复。
</details>

- **Token Optimization**: Minimizes LLM usage by prioritizing deterministic rules for assertions.
- **Robust Locators**: Uses stable accessibility references (`ref=eXX`) for interaction.
- **Global Goal Validation**: Supports defining high-level test goals (e.g., URL or text presence) that are verified at the end of every test execution.

## 📁 Project Structure

```text
.
├── artifacts/              # Centralized runtime artifacts (唯一归档目录)
│   ├── logs/               # Detailed execution logs
│   ├── traces/             # Recorded execution traces (raw)
│   ├── smoke_tests/        # Refined test specs (JSON/YAML) (统一冒烟目录)
│   ├── browser_profile*/    # Isolated browser profiles
│   └── reports/            # Screenshots and OCR debugging data

├── ai/
│   ├── llm_client.py       # Terminal interaction & AI verification interface
│   └── prompt_builder.py   # AI prompt engineering for decisions
├── ci/
│   ├── run_smoke_tests.py     # CI Orchestrator [NEW]
│   └── reporter.py            # Test Reporting Logic [NEW]
├── core/
│   ├── verification_engine.py # Rule-based + AI Verification Engine [NEW]
│   ├── snapshot_manager.py    # ARIA snapshot interface
│   ├── action_executor.py     # Browser action dispatcher
│   └── ocr_helper.py          # CAPTCHA and visual text recognition
├── runner/
│   └── test_runner.py      # Core async execution engine
├── tracer/                 # Trace System
│   ├── schema.py           # Extended JSON Trace Schema (Expected/Verification)
│   ├── recorder.py         # Step-by-step state & verification recorder
│   ├── evaluator.py        # Confidence calculation
│   └── replay_runner.py    # CLI for verification-aware playback
├── test_specs/
│   └── login_v2.yaml       # Specification with expected & goal fields
└── package.json            # Node.js dependencies (agent-browser)
```

## 🛠️ Installation

### 1. Prerequisites
- Python 3.11+
- Node.js & npm
- Playwright for Python (`pip install playwright`)

### 2. Setup
```bash
# Install Node dependencies
npm install agent-browser
npx agent-browser install
# Install Python dependencies

```
### 3. 主程序入口维护 (`run.py`)
- **唯一入口原则**: 为了防止命令行参数过于复杂，本项目提供 `python run.py` 作为统一交互入口。
- **强制同步**: **后续任何新增的脚本或功能，必须同步在 `run.py` 中增加对应的菜单项与参数引导逻辑。** 严禁发布只有复杂 CLI 参数而无交互引导的功能。

---
*提示：保持 `artifacts/` 作为唯一输出源，任何新增的临时配置文件严禁直接放置于项目根目录。*

## 🚀 Quick Start (快速开始)

最简单的使用方式是借助 **工业级交互式主入口**，它提供了分页选择、路径自适应搜索及批量执行能力：

```bash
# 启动统一交互入口
python run.py
```

执行后，您可以根据菜单选择功能：
1. **探索性测试**: 支持交互选择 pre-steps 前置步骤。
2. **定向脚本**: 具备 **智能分页文件选择器** (10条/页)，支持从 `test_specs` 或 `smoke_tests` 中点选脚本。
3. **轨迹回放**: 提供可视化轨迹选择列表，优先支持 `smoke_tests` 金牌轨迹回放。
4. **轨迹分析**: 对录制的原始轨迹进行聚类，提取核心冒烟用例。
5. **环境清理**: 强力回收残留进程与端口。
6. **自动化批量测试 [NEW]**: **工业化核心能力**。支持一键扫描目录（如 `smoke_tests`），执行全量回归。

---

### 原生命令行运行 (不推荐)
如果您需要自动化集成，仍可直接调用脚本：
- **探索测试**: `python runner/exploratory_runner.py <url> <steps>`
- **定向测试**: `python runner/test_runner.py <spec_path>`
- **回放**: `python tracer/replay_runner.py <trace_path>`

### Supported Verification Rules
- `url_contains`: Current URL contains specific substring.
- `url_equals`: Exact URL match.
- `text_present`: Global text search in page body.
- `element_visible`: Check if selector/ref is visible.
- `element_not_visible`: Check if selector/ref is hidden.
- `element_value_equals`: Check input value match (requires `selector`).

### Replaying a Trace
Replay mode now automatically checks recorded expectations using the Verification Engine:
```bash
python tracer/replay_runner.py artifacts/traces/raw/trace_login_v2_..._pass.json
```

## 📝 Test Case Format (YAML)
The new `v2` format supports modular **Pre-Steps** for logic reuse.

```yaml
name: "子系统遍历测试 (解耦版)"
url: "http://127.0.0.1:3000/"

# [NEW] 支持模块化加载前置步骤 (支持外部引用或内联列表)
pre_steps: pre_login.yaml 

goal:
  text_present: "工作台"

steps:
  - instruction: "点击门户子系统..."
    expected:
      type: "url_contains"
      value: "portal"
```
*Note: Any recorded traces using `pre_steps` are automatically **self-contained** (the pre-steps are baked into the JSON).*

## 🌟 Latest Enhancements (v1.5)

The framework has been significantly upgraded for better **AI Agent compatibility** and **Windows stability**:

- **🚨 Business Error Detection Engine**: Automatically detects non-standard UI barriers like "No Permission" modals, Toast messages, and system alerts via multi-layer heuristic scanning.
- **⌨️ Interactive Shortcut Commands**:
  - `+` Suffix: Chain multiple JSON commands without interruption (Automatic `task_status: in_progress`).
  - `exit/quit`: Cleanly terminate test execution and immediately recycle port resources.
- **🛡️ High Reliability Replay**: 
  - **Port Conflict (10048) Auto-Fix**: Advanced PowerShell process recycling for `node` and `agent-browser` daemons.
  - **Smart-Map Auto-Healing**: Dynamically remaps moved or changed elements using semantic attributes during playback.
- **🤖 Antigravity Certified**: This framework is optimized for and runs exceptionally well under the **Antigravity** coding assistant, featuring streamlined terminal prompts and detailed debug visibility.

### 📂 Trace Clustering & Smoke Test Extraction [NEW]
- **Structural Similarity**: Uses **LCS (Longest Common Subsequence)** to identify logically redundant paths, even with minor action variations.
- **Smart Deduplication**: Groups hundreds of raw exploratory traces into a few core "Golden Paths" using a Greedy Clustering algorithm.
- **Auto-evolving Tests**: Automatically selects the most stable and concise representative trace as a **Smoke Test**, inferring test goals from final state evidence.

<details>
<summary><b>🇨🇳 点击展开中文使用与特性说明 (Click to expand Chinese Usage & Enhancements)</b></summary>

### 快速开始 (快速上手)
1. **安装依赖**：`npm install agent-browser` 和 `pip install pydantic playwright pyyaml`。
2. **常规测试**：`python runner/test_runner.py test_specs/login_v2.yaml`。
3. **自主探索**：`python runner/exploratory_runner.py <URL> 30`。
4. **回放轨迹**：`python tracer/replay_runner.py <trace_json_path>`。
5. **聚类分析与提炼**：`python runner/trace_analyser.py --dir artifacts/traces/raw --output smoke_tests`。

### 🚀 最新增强功能 (v1.7)
- **📂 自动化批量测试**：支持对 `smoke_tests` 全量回归，产出 Pass/Fail 汇总报告。
- **📦 模块化 Pre-Steps**：支持 `pre_steps` 解耦，具备“脚本目录 + 工作目录”双路径自适应搜索。
- **✨ 智能分页选择器**：`run.py` 内置文件分页器，支持 10 条分页、翻页命令与数字点选。
- **🛡️ 轨迹自包含特性**：录制时的前置步骤自动固化到轨迹中，回放时零依赖。
- **📂 Trace 聚类系统**：基于 **LCS 动态规划算法** 实现海量测试轨迹的自动去重与分类。
- **🚨 业务报错探测**：已集成 30+ 常见业务报错关键字（无权限、系统故障等）的自动识别。
- **🤖 Antigravity 适配**：框架已针对 Antigravity 的决策逻辑进行了深度 Prompt 调优。
</details>

---
*Created for AI-driven QA workflows. Optimized for Antigravity.*
