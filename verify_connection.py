import sys
import io

# 兼容 Windows 终端 Emoji 输出
if sys.platform == "win32" and isinstance(sys.stdout, io.TextIOWrapper):
    sys.stdout.reconfigure(encoding='utf-8')

import os
import json
import requests
from dotenv import load_dotenv

# 加载配置
load_dotenv()

def test_api_connection():
    api_key = os.getenv("GOOGLE_API_KEY")
    base_url = os.getenv("AI_BASE_URL", "https://generativelanguage.googleapis.com/v1beta/openai/")
    model = os.getenv("AI_MODEL", "gemini-3.1-flash-lite-preview")
    proxy = os.getenv("AI_PROXY")

    print(f"🔍 正在测试 [Gemini 3.1 Thinking] API 连通性...")
    print(f"📡 代理设置: {proxy if proxy else '无'}")
    print(f"🤖 模型名称: {model}")
    print(f"🔗 基础端点: {base_url}")

    proxies = {"http": proxy, "https": proxy} if proxy else None
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json"
    }
    
    full_url = base_url.rstrip("/") + "/chat/completions"
    
    payload = {
        "model": model,
        "messages": [
            {"role": "user", "content": "Briefly explain why 'Gemini 3.1 Flash-Lite' is suitable for agentic tasks. Reply with 'Ready' at the end."}
        ],
        "reasoning_effort": "high",
        "max_tokens": 1000
    }

    try:
        response = requests.post(
            full_url,
            headers=headers,
            json=payload,
            proxies=proxies,
            timeout=60
        )
        
        if response.status_code != 200:
            print(f"❌ 连通性测试失败 (HTTP {response.status_code})")
            print(f"📑 错误详情: {response.text}")
            return False
            
        res_json = response.json()
        content = res_json["choices"][0]["message"]["content"].strip()
        
        print(f"✅ 连通性测试成功！")
        print(f"📩 AI 推理回复: {content}")
        return True
    except Exception as e:
        print(f"❌ 连通性测试异常: {str(e)}")
        return False

if __name__ == "__main__":
    test_api_connection()
