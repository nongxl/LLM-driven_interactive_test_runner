# coding:utf8
import os
import sys
import time

# 强制设置标准输出输出编码为 utf-8，解决 Windows 下的乱码问题
if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding='utf-8')
        sys.stderr.reconfigure(encoding='utf-8')
    except (AttributeError, Exception):
        import io
        sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
        sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8')

try:
    import ollama
except ImportError:
    print("\033[91m[错误] 未检测到 'ollama' 库。请运行: pip install ollama\033[0m")
    sys.exit(1)

# --- 终端颜色定义 ---
BLUE = "\033[94m"
GREEN = "\033[92m"
YELLOW = "\033[93m"
RED = "\033[91m"
BOLD = "\033[1m"
CYAN = "\033[96m"
RESET = "\033[0m"

def print_header():
    print(f"{BLUE}{BOLD}")
    print("="*60)
    print("      🦙 Ollama Local LLM Interaction Test (V1)        ")
    print("      > Model: gemma4:2b")
    print("="*60)
    print(f"{RESET}")

def chat_loop():
    model_name = 'gemma4:2b'
    messages = []
    
    print_header()
    print(f"{YELLOW}提示: 输入 'exit' 或 'quit' 退出对话，输入 'clear' 清空历史。{RESET}\n")
    
    while True:
        try:
            user_input = input(f"{GREEN}{BOLD}User > {RESET}").strip()
            
            if not user_input:
                continue
            
            if user_input.lower() in ['exit', 'quit', '退出']:
                print(f"\n{BLUE}再见！{RESET}")
                break
                
            if user_input.lower() == 'clear':
                messages = []
                print(f"{CYAN}[系统] 对话历史已清空。{RESET}\n")
                continue

            # 将用户输入加入历史
            messages.append({'role': 'user', 'content': user_input})
            
            print(f"\n{CYAN}{BOLD}Assistant > {RESET}", end="", flush=True)
            
            full_response = ""
            start_time = time.time()
            
            # 使用流式输出
            try:
                stream = ollama.chat(
                    model=model_name,
                    messages=messages,
                    stream=True,
                )
                
                for chunk in stream:
                    content = chunk['message']['content']
                    print(content, end="", flush=True)
                    full_response += content
                
                print("\n") # 结束行
                
                # 将助手回复加入历史
                messages.append({'role': 'assistant', 'content': full_response})
                
            except ollama.ResponseError as e:
                print(f"\n{RED}[Ollama 错误] {e.error}{RESET}")
                if "not found" in e.error.lower():
                    print(f"{YELLOW}提示: 请确保已运行 `ollama pull {model_name}`{RESET}")
                # 移除最后一条无效的用户消息
                messages.pop()
            except Exception as e:
                print(f"\n{RED}[连接错误] 无法连接到 Ollama 服务。{RESET}")
                print(f"{YELLOW}请检查: 1. Ollama 是否已启动? 2. 地址是否为 http://localhost:11434?{RESET}")
                # 移除最后一条无效的用户消息
                messages.pop()

        except KeyboardInterrupt:
            print(f"\n\n{YELLOW}[提示] 按下 Ctrl+C，正在退出...{RESET}")
            break

if __name__ == "__main__":
    chat_loop()