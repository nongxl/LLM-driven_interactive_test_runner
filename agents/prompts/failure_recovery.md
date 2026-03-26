# 失败恢复 Prompt

## 用途

当测试执行失败时，分析失败原因并尝试恢复。

## 失败类型

### 元素定位失败

**症状**: 找不到指定的元素

**可能原因**:
- 页面未完全加载
- 元素描述不准确
- 页面结构变化
- 元素被遮挡或隐藏

**恢复策略**:
1. 等待页面加载完成
2. 重新获取页面快照
3. 更新元素描述
4. 尝试滚动到元素位置

### 操作执行失败

**症状**: 找到元素但操作失败

**可能原因**:
- 元素不可交互
- 元素被禁用
- 操作时机不对
- 弹窗遮挡

**恢复策略**:
1. 检查元素状态
2. 等待元素可交互
3. 处理弹窗
4. 重试操作

### 断言失败

**症状**: 预期结果与实际结果不符

**可能原因**:
- 业务逻辑错误
- 数据状态不对
- 页面显示延迟
- 环境问题

**恢复策略**:
1. 检查数据状态
2. 等待页面稳定
3. 重新执行前置步骤
4. 记录详细信息

## 恢复流程

### 第一步：信息收集

```python
# 收集失败信息
failure_info = {
    "error_type": "element_not_found",
    "element_description": "登录按钮",
    "page_url": browser.get_url(),
    "page_title": browser.get_title(),
    "screenshot": browser.take_screenshot(),
    "snapshot": browser.get_snapshot()
}
```

### 第二步：原因分析

根据收集的信息分析失败原因：

| 错误类型 | 分析重点 |
|----------|----------|
| 元素定位失败 | 检查快照中是否存在该元素 |
| 操作执行失败 | 检查元素状态和页面状态 |
| 断言失败 | 检查实际值和预期值的差异 |

### 第三步：尝试恢复

根据分析结果尝试恢复：

```python
# 等待页面稳定
browser.wait_for_page_load()

# 重新获取快照
snapshot = browser.get_snapshot()

# 重新分析元素
element = analyze_element(snapshot, element_description)

# 重试操作
browser.click(element)
```

### 第四步：记录结果

无论恢复成功与否，都记录详细信息：

```python
# 记录到日志
logger.log_failure(failure_info)

# 保存截图和快照
save_artifacts(failure_info)
```

## 恢复策略详解

### 等待策略

```python
# 等待页面加载
browser.wait_for_load_state("networkidle")

# 等待元素出现
browser.wait_for_element("登录按钮", timeout=10000)

# 等待元素可交互
browser.wait_for_element_state("登录按钮", "visible")
browser.wait_for_element_state("登录按钮", "enabled")
```

### 重试策略

```python
# 带重试的操作
def click_with_retry(description: str, max_retries: int = 3):
    for attempt in range(max_retries):
        try:
            browser.click(description)
            return True
        except Exception as e:
            if attempt == max_retries - 1:
                raise
            browser.wait(1000)
    return False
```

### 弹窗处理

```python
# 检查并处理弹窗
def handle_popup():
    if browser.is_visible("确认按钮"):
        browser.click("确认按钮")
    elif browser.is_visible("关闭按钮"):
        browser.click("关闭按钮")
```

## 失败报告

### 报告内容

```json
{
  "test_name": "test_login",
  "failure_time": "2026-03-11T10:30:00",
  "error_type": "element_not_found",
  "error_message": "无法找到元素: 登录按钮",
  "page_url": "https://example.com/login",
  "page_title": "用户登录",
  "recovery_attempted": true,
  "recovery_successful": false,
  "artifacts": {
    "screenshot": "artifacts/screenshots/test_login_failure.png",
    "snapshot": "artifacts/snapshots/test_login_failure.json"
  }
}
```

## 最佳实践

### DO

- 收集详细的失败信息
- 尝试合理的恢复策略
- 记录恢复过程
- 保存失败现场

### DON'T

- 不要无限重试
- 不要忽略失败
- 不要跳过信息收集
- 不要丢失失败现场

## 预防措施

### 测试设计

- 使用明确的等待条件
- 添加适当的断言
- 设计可恢复的测试流程

### 代码实现

- 封装常用的恢复逻辑
- 使用 Page Object 隔离变化
- 记录关键操作日志

### 环境准备

- 确保测试环境稳定
- 准备干净的测试数据
- 监控环境状态
