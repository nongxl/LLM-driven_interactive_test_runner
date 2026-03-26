# 元素定位 Prompt

## 用途

根据语义描述定位页面元素，不使用 CSS selector 或 XPath。

## 定位原则

### 语义化定位

- 使用元素的语义描述定位
- 使用用户可见的文本内容
- 使用元素的 ARIA 属性

### 避免使用

- CSS selector
- XPath
- 动态生成的 id 或 class
- 不稳定的属性

## 定位策略

### 优先级顺序

1. **文本内容**: 使用元素显示的文本
2. **ARIA 标签**: 使用 aria-label, aria-labelledby
3. **语义标签**: 使用语义化的 HTML 标签
4. **位置描述**: 使用相对位置描述

### 定位方法

#### 文本定位

```python
# 通过文本内容定位
browser.click("登录")
browser.fill("用户名", "testuser")
```

#### 标签组合定位

```python
# 通过标签和文本组合
browser.click("button:登录")
browser.fill("input:用户名", "testuser")
```

#### 区域定位

```python
# 通过区域限定
browser.click("登录表单中的登录按钮")
browser.fill("搜索区域中的输入框", "关键词")
```

## 定位描述格式

### 基本格式

```
[区域]元素类型:元素描述
```

### 示例

| 描述 | 含义 |
|------|------|
| `登录按钮` | 文本为"登录"的按钮 |
| `用户名输入框` | 标签为"用户名"的输入框 |
| `导航栏中的首页链接` | 导航栏区域内的"首页"链接 |
| `表单中的提交按钮` | 表单区域内的提交按钮 |

## 处理复杂场景

### 重复元素

当页面有多个相同描述的元素时：

```python
# 使用序号
browser.click("第二个登录按钮")

# 使用区域限定
browser.click("顶部导航栏的登录按钮")
```

### 动态元素

当元素文本动态变化时：

```python
# 使用部分匹配
browser.click("包含'确认'的按钮")

# 使用正则模式
browser.click("匹配 /提交.*/ 的按钮")
```

### 隐藏元素

当元素不可见时：

```python
# 先使元素可见
browser.scroll_to("底部按钮")
browser.click("底部按钮")
```

## 定位失败处理

### 重试策略

1. 重新获取页面快照
2. 分析页面变化
3. 调整定位描述
4. 尝试替代定位方式

### 失败记录

记录以下信息：
- 原始定位描述
- 页面快照
- 失败原因
- 替代方案

## 最佳实践

### DO

- 使用语义化描述
- 使用用户可见的文本
- 保持描述简洁明了
- 使用区域限定提高准确性

### DON'T

- 不要使用 CSS selector
- 不要使用 XPath
- 不要使用不稳定的属性
- 不要过度依赖元素顺序

## 示例场景

### 登录页面

```python
# 语义化定位
login_page.fill_username("testuser")
login_page.fill_password("password123")
login_page.click_login()

# 对应的语义描述
# fill_username -> 填充 "用户名输入框"
# fill_password -> 填充 "密码输入框"  
# click_login -> 点击 "登录按钮"
```

### 搜索页面

```python
# 语义化定位
search_page.enter_keyword("playwright")
search_page.click_search()
search_page.click_first_result()

# 对应的语义描述
# enter_keyword -> 填充 "搜索输入框"
# click_search -> 点击 "搜索按钮"
# click_first_result -> 点击 "第一个搜索结果"
```
