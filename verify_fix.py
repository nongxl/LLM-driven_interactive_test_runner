import asyncio
import os
import sys

# Ensure ROOT is in path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__))))

from runner.exploratory_runner import run_exploratory_test

async def main():
    os.environ["TEST_DEBUG"] = "0"
    url = "http://192.168.20.132:3000/"
    print(f"🚀 Starting Verification Test on {url}...")
    # Run for 3 steps to verify log suppression and stability
    await run_exploratory_test(url, max_steps=3, interactive=False)
    print("✅ Verification Test Completed.")

if __name__ == "__main__":
    asyncio.run(main())
