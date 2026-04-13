
import asyncio
from playwright.async_api import async_playwright
import requests

async def close_browser_pages():
    try:
        # 尝试连接 agent-browser 暴露的 3030 端口获取正在运行的浏览器信息
        response = requests.get("http://127.0.0.1:3030/json/version")
        if response.status_code == 200:
            cdp_url = response.json().get('webSocketDebuggerUrl')
            print(f"Connecting to CDP: {cdp_url}")
            async with async_playwright() as p:
                browser = await p.chromium.connect_over_cdp(cdp_url)
                pages = browser.contexts[0].pages
                print(f"Found {len(pages)} pages. Closing them...")
                for page in pages:
                    await page.close()
                await browser.close()
                print("Pages closed.")
        else:
            print("Could not get CDP info from 3030.")
    except Exception as e:
        print(f"Error: {e}")

if __name__ == "__main__":
    asyncio.run(close_browser_pages())
