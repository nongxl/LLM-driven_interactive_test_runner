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
        res = await page.evaluate('''() => {
            return {
                body_html: document.body.innerHTML,
                body_children: document.body.children.length,
                doc_html: document.documentElement.innerHTML,
                iframes: document.querySelectorAll('iframe').length,
                shadows: Array.from(document.querySelectorAll('*')).filter(el => el.shadowRoot).length
            }
        }''')
        print(f"Body Children: {res['body_children']}")
        print(f"Iframes: {res['iframes']}")
        print(f"Shadows: {res['shadows']}")
        print(f"Full HTML Length: {len(res['doc_html'])}")
        print(f"HTML Snippet: {res['doc_html'][:2000]}")
    else:
        print("No page found")

if __name__ == "__main__":
    asyncio.run(check())
