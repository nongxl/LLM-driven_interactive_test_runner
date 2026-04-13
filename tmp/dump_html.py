import asyncio
import os
import sys

# Add root to sys.path
sys.path.insert(0, os.getcwd())

from core.verification_engine import get_playwright_page, initialize_verification_engine

async def check():
    await initialize_verification_engine()
    page = await get_playwright_page()
    if page:
        print(f"URL: {page.url}")
        content = await page.content()
        with open("artifacts/tmp/page_content.html", "w", encoding="utf-8") as f:
            f.write(content)
        print("Content saved to artifacts/tmp/page_content.html")
    else:
        print("No page found")

if __name__ == "__main__":
    asyncio.run(check())
