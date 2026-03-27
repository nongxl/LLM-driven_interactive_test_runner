import asyncio
import os
import sys

# 确保能找到 core 模块
sys.path.insert(0, os.path.abspath(os.path.dirname(__file__)))

from core.verification_engine import initialize_verification_engine, get_playwright_page, verify, close_verification_engine

async def test_debug_save():
    print("开始测试断言失败调试保存功能...")
    
    # 1. 启动引擎
    success = await initialize_verification_engine()
    if not success:
        print("❌ 无法初始化验证引擎")
        return

    page = await get_playwright_page()
    if not page:
        print("❌ 无法获取 Page 对象")
        return

    # 2. 导航到一个已知页面
    print("正在导航到 http://127.0.0.1:3000 (本地前端)...")
    try:
        await page.goto("http://127.0.0.1:3000", timeout=5000)
    except:
        print("⚠️ 无法访问本地 3000 端口，尝试访问 Google...")
        await page.goto("https://www.google.com", timeout=10000)

    # 3. 执行一个必然失败的断言
    expected = {
        "type": "text_present",
        "value": "THIS_STRING_DEFINITELY_DOES_NOT_EXIST_999999"
    }
    
    snapshot_id = "test_snap_12345"
    print(f"正在执行断言 (预期失败，快照ID: {snapshot_id})...")
    
    result = await verify(page, expected, snapshot_id=snapshot_id)
    print(f"断言结果: {result['result']} - {result['reason']}")

    # 4. 检查文件是否存在
    tmp_dir = os.path.join(os.getcwd(), 'artifacts', 'tmp')
    found_files = []
    if os.path.exists(tmp_dir):
        for f in os.listdir(tmp_dir):
            if snapshot_id in f:
                found_files.append(f)
    
    if found_files:
        print(f"✅ 成功! 发现关联文件: {found_files}")
    else:
        print("❌ 失败! 未发现关联的调试文件。")

    await close_verification_engine()

if __name__ == "__main__":
    asyncio.run(test_debug_save())
