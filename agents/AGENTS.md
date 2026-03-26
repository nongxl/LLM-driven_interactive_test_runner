# AI Agent 工作规则

## 项目目标

构建基于 agent-browser 的网页自动化测试框架，实现 AI 辅助开发（vibe coding）。

核心目标：
- 结构清晰，便于 AI 理解
- 减少上下文消耗
- 避免重复推理
- 避免 AI 陷入循环修改代码
- 易于长期维护

## 架构原则

### 语义化 Page Object Model

采用适配 agent-browser 的语义化 Page Object Model：

**重要原则：**
- 不要在代码中存储 CSS selector 或 XPath
- 元素定位应依赖 agent-browser 的 snapshot 机制
- Page Object 只表达页面语义和用户操作
- 不要表达 DOM 结构

### 分层架构

```
tests/      -> 测试用例（调用 flow）
flows/      -> 业务流程（组合多个页面操作）
pages/      -> 页面对象（页面级操作）
utils/      -> 工具类
config/     -> 配置
```

## AI 编码规则

### 代码组织规则

1. **不要在 tests 中写业务逻辑**
   - tests 只负责调用 flow 和断言
   - 业务逻辑必须在 flows 中实现

2. **复杂用户流程必须写在 flows 中**
   - 一个 flow 可以组合多个页面操作
   - flow 封装完整的业务场景

3. **页面操作写在 pages 中**
   - 每个页面只负责该页面的操作
   - 页面之间不直接调用

4. **不要存储 CSS selector**
   - 元素定位依赖 snapshot 推理
   - 优先使用语义描述

### 代码风格规则

1. **保持简单清晰**
   - 不要过度抽象
   - 代码可读性优先

2. **避免重复推理**
   - 相同逻辑只实现一次
   - 复用现有代码

3. **避免循环修改**
   - 一次修改到位
   - 不要反复重构

## Agent 工作流程

### 任务执行流程

1. 阅读 TASKS.md 获取当前任务
2. 选择一个任务标记为 in_progress
3. 实现任务
4. 标记任务为 completed
5. 更新 MEMORY.md

### 文件修改规则

1. 新增文件前先更新 PROJECT_STRUCTURE.md
2. 修改结构前先更新 PROJECT_STRUCTURE.md
3. 保持文档与代码同步

### 问题处理流程

1. 遇到问题先查阅 MEMORY.md
2. 查看 agents/prompts/ 下的相关 prompt
3. 记录解决方案到 MEMORY.md

## 技能策略

### 可用 Skills

| Skill | 用途 | 使用场景 |
|-------|------|----------|
| agent-browser | 网页自动化 | 默认使用，用于稳定测试流程 |
| dogfood | 探索性测试 | 页面理解、探索性测试 |
| electron | Electron 应用 | 仅用于 Electron 应用测试 |
| slack | 通知发送 | 发送测试报告或通知 |

### 使用原则

1. 默认使用 agent-browser 进行网页自动化
2. dogfood 只用于探索性测试或页面理解
3. electron 仅用于 Electron 应用
4. slack 只用于发送通知或报告
5. 不要在稳定测试流程中频繁切换 skills

## 协作方式

### 与 AI Agent 协作

1. AI Agent 通过阅读本文档理解项目规则
2. 通过 TASKS.md 获取任务
3. 通过 MEMORY.md 了解项目状态
4. 通过 SKILLS.md 了解可用技能

### 文档更新规则

- 每次完成任务后更新 TASKS.md
- 每次重要变更后更新 MEMORY.md
- 结构变更时更新 PROJECT_STRUCTURE.md
