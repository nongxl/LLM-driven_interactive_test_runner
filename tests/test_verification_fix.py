import asyncio
import os
import sys
from playwright.async_api import async_playwright

# 将项目根目录添加到路径
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from core.verification_engine import verify, initialize_verification_engine, get_playwright_page

async def main():
    # 使用本地 playwright 而不是连接到 agent-browser 同步模型，模拟连接
    async with async_playwright() as p:
        browser = await p.chromium.launch()
        context = await browser.new_context()
        page = await context.new_page()
        
        # 加载测试文件
        test_file = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', 'artifacts', 'tmp', 'test_fix.html'))
        url = f"file:///{test_file}".replace("\\", "/")
        await page.goto(url)
        print(f"Navigated to {url}")
        
        # 1. 验证 placeholder 匹配
        print("\nTesting placeholder '账号'...")
        res1 = await verify(page, {"type": "text_present", "value": "账号"})
        print(f"Result: {res1['result']} - {res1['reason']}")
        
        # 2. 验证 title 匹配
        print("\nTesting title attribute '点击提交'...")
        res2 = await verify(page, {"type": "text_present", "value": "点击提交"})
        print(f"Result: {res2['result']} - {res2['reason']}")
        
        # 3. 验证输入值匹配
        print("\nTesting input value 'admin'...")
        await page.fill("#user-input", "admin")
        res3 = await verify(page, {"type": "text_present", "value": "admin"})
        print(f"Result: {res3['result']} - {res3['reason']}")
        
        # 4. 验证失败后的调试文件
        print("\nTesting failure debug artifact...")
        res4 = await verify(page, {"type": "text_present", "value": "不存在的文本"}, snapshot_id="test_fail")
        print(f"Result: {res4['result']} - {res4['reason']}")
        
        await browser.close()
        
        # 检查调试文件内容
        debug_txt = os.path.join(os.path.dirname(__file__), '..', 'artifacts', 'tmp', 'fail_test_fail.txt')
        if os.path.exists(debug_txt):
            with open(debug_txt, 'r', encoding='utf-8') as f:
                content = f.read()
                print(f"\nDebug TXT content length: {len(content)}")
                # 确认是否包含 placeholder 文本
                if "账号" in content:
                    print("SUCCESS: Debug TXT contains placeholder text!")
                else:
                    print("FAILURE: Debug TXT missing placeholder text!")
        else:
            print("FAILURE: Debug TXT file not found!")

if __name__ == "__main__":
    asyncio.run(main())
