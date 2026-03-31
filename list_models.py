import sys
import io

# 兼容 Windows 终端 Emoji 输出
if sys.platform == "win32" and isinstance(sys.stdout, io.TextIOWrapper):
    sys.stdout.reconfigure(encoding='utf-8')

import os
import requests
from dotenv import load_dotenv

# 加载配置
load_dotenv()

def list_models():
    api_key = os.getenv("GOOGLE_API_KEY")
    proxy = os.getenv("AI_PROXY")
    
    # 尝试列出模型 (使用 Google 原生 API 模式)
    url = f"https://generativelanguage.googleapis.com/v1beta/models?key={api_key}"
    print(f"🔍 正在列出可用模型...")
    
    proxies = {"http": proxy, "https": proxy} if proxy else None

    try:
        response = requests.get(url, proxies=proxies, timeout=30)
        response.raise_for_status()
        res_json = response.json()
        print("✅ 成功获取模型列表:")
        for model in res_json.get("models", []):
            name = model.get("name", "")
            display_name = model.get("displayName", "")
            supported_methods = model.get("supportedGenerationMethods", [])
            if "generateContent" in supported_methods:
                print(f"  - {name} ({display_name})")
    except Exception as e:
        print(f"❌ 列出模型失败: {str(e)}")
        if hasattr(e, 'response') and e.response is not None:
             print(f"📑 错误详情: {e.response.text}")

if __name__ == "__main__":
    list_models()
