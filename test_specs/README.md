# Test Specifications (YAML-driven)

本目录存放 **声明式测试规格 (Declarative Test Specs)**，作为自动化测试的唯一需求来源。目前系统已全面从 Markdown 转向 **YAML 格式**，以支持高度的结构化验证与逻辑解耦。

## 📁 目录结构

```text
test_specs/
├── pre_login.yaml          # [推荐] 公共登录前置逻辑 (模块化脚本)
├── check_navigator_links.yaml # 核心业务遍历用例 (包含前置引用)
└── ...                     # 其他特定业务脚本
```

## 📝 测试规格格式 (v2)

每个测试规格文件使用以下 YAML 结构：

```yaml
name: "测试用例名称 (必填)"
url: "起始访问网址 (必填)"

# [OPTIONAL] 前置步骤引用：支持外部文件名或内联步骤列表
# 例如: pre_steps: "pre_login.yaml" 或内联 [- instruction: "...", expected: {...}]
pre_steps: "pre_login.yaml" 

# [REQUIRED] 全局测试目标：测试结束时的最终验证条件
goal:
  text_present: "工作台"       # 支持 url_contains, text_present 等

# [REQUIRED] 测试执行步骤：AI 驱动的操作指令序列
steps:
  - instruction: "操作指令 (如：点击'系统管理'菜单)" # 自然语言描述
    expected:                                      # [可选] 每步执行后的预期校验条件
      type: "url_contains"
      value: "system/index"
```

## 🛠️ 核心能力说明

### 1. 模块化前置 (Pre-Steps)
为了减少重复劳动（如每个脚本都写登录），推荐将登录逻辑抽离至 `pre_login.yaml`。在业务脚本中通过 `pre_steps` 字段一键引用，实现“逻辑解耦、快速启动”。

### 2. 多重校验引擎 (Verification Engine)
- **规则校验**：优先使用 `url_contains`, `text_present`, `element_visible` 等确定性规则，速度最快，精度最高。
- **AI 动态校验**：对于复杂的 UI 变化，支持作为 `expected` 的兜底方案。

### 3. 轨迹自包含 (Self-Containment)
一旦通过 `test_runner.py` 完成录制，生成的 `.json` 轨迹会**自动包含** `pre_steps` 中的每一个动作。回放轨迹时无需再额外关注前置依赖。

## 🎯 编写准则 (DOs & DON'Ts)

### ✅ DO (推荐)
- **用户视角引导**：使用“点击XX按钮”、“输入XX”等人类可读指令，而非 CSS 选择器。
- **声明式目标**：明确 `goal` 作为最终断言，确保测试“有始有终”。
- **单步验证**：在关键步骤增加 `expected`，有助于 AI 在出错时立即上报。

### ❌ DON'T (禁止)
- **硬编码元素 ID**：脚本中严禁出现 `#id_123` 或 `.btn-primary` 等 DOM 结构耦合。
- **假设环境状态**：始终通过 `pre_steps` 显式描述测试所需的状态（如登录态）。

## 🚀 启动方式

```bash
# 推荐方式：通过统一入口点选
python run.py -> 选择 [2. 定向脚本测试]

# 原生方式
python runner/test_runner.py test_specs/your_spec.yaml
```

---
*Created for LLM-driven Industrial QA workflows.*
