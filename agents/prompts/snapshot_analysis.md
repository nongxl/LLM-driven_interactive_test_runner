# Snapshot 分析 Prompt

## 用途

分析 agent-browser 返回的页面快照，理解页面结构和元素。

## 输入

页面快照（snapshot）数据，包含：
- 页面 URL
- 页面标题
- 元素树结构
- 元素属性

## 分析任务

### 1. 页面识别

- 确认当前页面类型
- 识别页面主要区域
- 理解页面布局结构

### 2. 元素识别

对于每个需要操作的元素，识别：

| 属性 | 描述 |
|------|------|
| 元素类型 | button, input, link, text 等 |
| 语义描述 | 元素的功能和用途 |
| 可见性 | 是否可见、可交互 |
| 唯一标识 | 如何在页面中定位该元素 |

### 3. 操作映射

将用户操作映射到具体元素：

```
用户操作 -> 元素描述 -> 元素定位策略
```

## 输出格式

### 页面分析结果

```json
{
  "page_type": "login_page",
  "url": "/login",
  "title": "用户登录",
  "main_regions": [
    {
      "name": "登录表单",
      "elements": ["用户名输入框", "密码输入框", "登录按钮"]
    }
  ]
}
```

### 元素分析结果

```json
{
  "elements": [
    {
      "semantic_name": "用户名输入框",
      "type": "input",
      "description": "用于输入用户名的文本框",
      "locatable_by": "placeholder '请输入用户名'"
    },
    {
      "semantic_name": "登录按钮",
      "type": "button",
      "description": "提交登录表单的按钮",
      "locatable_by": "text '登录'"
    }
  ]
}
```

## 分析原则

### 语义优先

- 优先使用元素的语义含义
- 避免依赖技术属性（如 id, class）
- 使用用户视角的描述

### 稳定性优先

- 选择稳定的定位方式
- 避免依赖动态生成的属性
- 优先使用文本内容和语义标签

### 简洁优先

- 只分析必要的元素
- 避免过度分析
- 保持输出简洁明了

## 示例

### 输入

```
页面快照显示：
- 一个包含 "用户名" 标签的输入框
- 一个包含 "密码" 标签的输入框
- 一个 "登录" 按钮
- 一个 "忘记密码" 链接
```

### 输出

```json
{
  "page_type": "login_page",
  "elements": [
    {
      "semantic_name": "用户名输入框",
      "type": "input",
      "description": "用户名输入字段",
      "locatable_by": "label '用户名'"
    },
    {
      "semantic_name": "密码输入框",
      "type": "input",
      "description": "密码输入字段",
      "locatable_by": "label '密码'"
    },
    {
      "semantic_name": "登录按钮",
      "type": "button",
      "description": "提交登录",
      "locatable_by": "text '登录'"
    }
  ]
}
```

## 使用场景

1. **新页面理解**: 第一次访问页面时，分析页面结构
2. **元素定位失败**: 当元素定位失败时，重新分析快照
3. **页面变更**: 页面结构变化时，更新元素映射
