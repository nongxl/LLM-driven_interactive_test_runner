import re

def test_regex():
    # 模拟 agent-browser 产出的特定 ARIA Tree
    aria_text = """
    - link "首页" [ref=e1]
    - generic "业务控制中心" [ref=e5, focusable=True, clickable=True]
    - generic "系统设置" [ref=e6, clickable=True]
    - button "提交" [ref=e10]
    """
    
    # 新正则
    pattern = r'- (button|link|textbox|checkbox|combobox|menuitem|tab|generic)\s+"([^"]*)"\s+\[ref=(e\d+)(?:,[^\]]*clickable=True|[^\]]*)\]'
    
    matches = re.finditer(pattern, aria_text)
    found = []
    for m in matches:
        found.append({
            "role": m.group(1),
            "name": m.group(2),
            "ref": m.group(3)
        })
    
    print(f"找到元素数量: {len(found)}")
    for item in found:
        print(f"  [{item['role']}] {item['name']} (ref: {item['ref']})")

    # 验证是否抓到了 generic 且 clickable 的元素
    clickable_generic = [i for i in found if i['role'] == 'generic' and '业务控制中心' in i['name']]
    if clickable_generic:
        print("\n✅ 成功匹配到带有 clickable=True 的 generic 元素！")
    else:
        print("\n❌ 未能匹配到目标元素。")

if __name__ == "__main__":
    test_regex()
