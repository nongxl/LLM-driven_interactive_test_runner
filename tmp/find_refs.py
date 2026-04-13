import asyncio
import json
import os
import sys

# 修正目录
sys.path.append(os.getcwd())

from core.snapshot_manager import get_snapshot

async def main():
    print("正在抓取快照并提取 Ref 映射...")
    res = await get_snapshot()
    aria = res.get("aria_text", "")
    refs = res.get("refs", {})
    
    print("\n--- ARIA Tree Excerpt (Lines 50-250) ---")
    lines = aria.split('\n')
    for line in lines[50:250]:
        print(line)
        
    print("\n--- Filter Keywords Analysis ---")
    keywords = ["企业名称", "任务名称", "查询", "重置", "展开"]
    for kw in keywords:
        for ref, text in refs.items():
            if kw in text:
                print(f"找到关键词 '{kw}': ref={ref}, text={text}")

if __name__ == "__main__":
    asyncio.run(main())
