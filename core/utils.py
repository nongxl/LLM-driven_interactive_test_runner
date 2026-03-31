import os
import sys
import time
import shutil
import subprocess
import re

def strip_ansi(text: str) -> str:
    """过滤字符串中的 ANSI 转义码"""
    ansi_escape = re.compile(r'\x1B(?:[@-Z\\-_]|\[[0-?]*[ -/]*[@-~])')
    return ansi_escape.sub('', text)

# 全局兼容性标记
S_OK = "[OK]"
S_ERR = "[FAIL]"
S_WARN = "[WARN]"
S_INFO = "[INFO]"

def resolve_trace_path(path: str) -> str:
    """尝试智能识别 Trace 文件路径"""
    if not path: return path
    if os.path.exists(path):
        return path
    
    # 尝试加上 artifacts 前缀
    alt_path = os.path.join("artifacts", path)
    if os.path.exists(alt_path):
        return alt_path
        
    # 尝试在 artifacts/traces/raw 下寻找
    if not path.startswith("artifacts"):
        base_name = os.path.basename(path)
        common_path = os.path.join("artifacts", "traces", "raw", base_name)
        if os.path.exists(common_path):
            return common_path
            
    return path

def cleanup_browser_env(port=None, profile_name="browser_profile", logger=None, force_clean=False):
    """
    通用浏览器环境清理工具。
    
    :param port: 可选，指定要清理的端口
    :param profile_name: 要清理的 profile 目录名称
    :param logger: 日志记录函数
    :param force_clean: True 时才删除 Profile 目录和 tmp（仅由菜单选项5触发）
                        False（默认）时只清理进程和端口，不动任何文件
    """
    if logger is None:
        logger = print

    mode_label = "[完整清理]" if force_clean else "[进程清理]"
    logger(f"\n[Cleanup] {mode_label} 正在清理环境 (Profile: {profile_name})...")
    
    # 1. 强力终止所有相关进程 (针对 Windows)
    try:
        if sys.platform == "win32":
            # 定义需要清理的端口
            target_ports = [3000, 3030, 3031]
            if port:
                try: target_ports.append(int(port))
                except: pass
            
            # A. 快速清理：优先使用 taskkill 杀掉纯自动化工具进程（免去启动 PowerShell 的开销）
            pure_automation_names = ['node.exe', 'chromedriver.exe', 'msedgedriver.exe', 'agent-browser.exe']
            for name in pure_automation_names:
                subprocess.run(['taskkill', '/F', '/IM', name, '/T'], capture_output=True, timeout=5)
            
            # B. 精准停止：仅对带自动化 Profile 的浏览器使用 PowerShell 过滤 (增加 15s 强制超时)
            # 这里的 profile_name 默认为 browser_profile
            search_pattern = profile_name if profile_name else "browser_profile"
            ps_kill_browsers = f'Get-CimInstance Win32_Process -Filter "Name = \'chrome.exe\' OR Name = \'msedge.exe\'" | Where-Object {{ $_.CommandLine -like "*{search_pattern}*" }} | ForEach-Object {{ Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }}'
            
            # C. 端口清理 (增加 15s 强制超时)
            ps_kill_ports = ""
            for p in list(set(target_ports)):
                ps_kill_ports += f'Get-NetTCPConnection -LocalPort {p} -ErrorAction SilentlyContinue | ForEach-Object {{ Stop-Process -Id $_.OwningProcess -Force -ErrorAction SilentlyContinue }} ; '
            
            full_ps = f'{ps_kill_browsers} ; {ps_kill_ports}'
            try:
                subprocess.run(['powershell', '-Command', full_ps], capture_output=True, timeout=15)
                logger(f" [OK] 已完成进程清理与端口回收")
            except subprocess.TimeoutExpired:
                logger(f" [Warn] PowerShell 清理阶段由于超时 (15s) 被强制终止")
            except KeyboardInterrupt:
                logger(f" [Warn] 进程清理被用户手动中断")
                raise
        else:
            # Linux/Mac 简单处理 (由于通常是 headless 运行，误杀风险较小)
            subprocess.run(["pkill", "-9", "-f", "node"], capture_output=True)
            # Linux/Mac 上可以通过 -f 匹配命令行参数
            subprocess.run(["pkill", "-9", "-f", profile_name or "browser_profile"], capture_output=True)
    except Exception as e:
        logger(f" [Warn] 进程清理异常: {e}")
    
    # 2. 清理 Profile 目录（仅在 force_clean=True 时执行）
    if not force_clean:
        logger(f" [Skip] Profile 目录保留（日常测试模式），登录状态复用")
    else:
        import glob
        target_patterns = []
        if profile_name is None or profile_name == "browser_profile":
            target_patterns = [os.path.join(os.getcwd(), 'artifacts', 'browser_profile*')]
        else:
            target_patterns = [os.path.join(os.getcwd(), 'artifacts', profile_name)]

        for pattern in target_patterns:
            for p_path in glob.glob(pattern):
                if os.path.isdir(p_path):
                    p_name = os.path.basename(p_path)
                    logger(f" [Action] 正在清理 Profile: {p_name}...");
                    success = False
                    for i in range(5):
                        try:
                            # 即使在 force_clean 下，也优先尝试精准杀掉占用该目录的进程
                            if sys.platform == "win32":
                                subprocess.run(['powershell', '-Command', f'Get-CimInstance Win32_Process | Where-Object {{$_.CommandLine -like "*{p_name}*"}} | ForEach-Object {{ Stop-Process -Id $_.ProcessId -Force }}'], capture_output=True)
                            
                            time.sleep(i + 1)
                            shutil.rmtree(p_path)
                            logger(f" [OK] {p_name} 目录已清理")
                            success = True
                            break
                        except Exception as e:
                            if i < 4:
                                logger(f" [Retry] 正在重试 ({i+1}/5): {str(e)[:50]}...")
                            else:
                                try:
                                    rename_path = p_path + "_old_" + str(int(time.time()))
                                    os.rename(p_path, rename_path)
                                    logger(f" [OK] {p_name} 已重命名为 {os.path.basename(rename_path)}")
                                    success = True
                                except:
                                    logger(f" [Warn] 目录 {p_name} 清理失败: {e}")

    # 3. 清理 artifacts/tmp 目录（仅在 force_clean=True 时执行）
    if force_clean:
        tmp_path = os.path.join(os.getcwd(), 'artifacts', 'tmp')
        if os.path.exists(tmp_path):
            try:
                shutil.rmtree(tmp_path)
                os.makedirs(tmp_path, exist_ok=True)
                logger(f" [OK] artifacts/tmp 目录已清空")
            except Exception as e:
                logger(f" [Warn] artifacts/tmp 清理失败: {e}")

def is_port_alive(port):
    """检测指定的本地 TCP 端口是否正在运行服务"""
    import socket
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.settimeout(0.5) # 极快探测
            return s.connect_ex(('127.0.0.1', int(port))) == 0
    except:
        return False

def get_agent_browser_executable():
    """获取 agent-browser 的可执行方案 (优先使用本项目 node_modules)"""
    import os
    # 路径 A: 项目根目录下的 node_modules/.bin (这也是 npx 默认会寻找的地方)
    # 使用 os.getcwd() 确保是在用户运行 run.py 的位置寻找
    local_bin_name = 'agent-browser.cmd' if os.name == 'nt' else 'agent-browser'
    local_bin = os.path.join(os.getcwd(), 'node_modules', '.bin', local_bin_name)
    
    if os.path.exists(local_bin):
        return f'"{os.path.abspath(local_bin)}"'
    
    # 路径 B: 如果 cwd 不在根目录，尝试相对于本文件所在位置向上找
    alt_bin = os.path.join(os.path.dirname(__file__), '..', 'node_modules', '.bin', local_bin_name)
    if os.path.exists(alt_bin):
        return f'"{os.path.abspath(alt_bin)}"'

    # 降级方案: npx (带 -y)
    return 'npx.cmd -y' if os.name == 'nt' else 'npx -y'

