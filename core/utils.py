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
            
            # 停止浏览器和 Node 进程
            process_names = ['node', 'chrome', 'msedge', 'chromedriver', 'msedgedriver', 'agent-browser']
            # 使用逗号连接进程名，并增加 Try/Catch
            plist_str = ",".join([f"'{p}'" for p in process_names])
            ps_kill_procs = f'$plist = @({plist_str}) ; foreach($p in $plist) {{ Stop-Process -Name $p -Force -ErrorAction SilentlyContinue }}'
            
            # 清理端口占用 (增加精准打击)
            ps_kill_ports = ""
            for p in list(set(target_ports)):
                # 这里不仅杀 OwningProcess，还尝试杀掉任何监听该端口的进程
                ps_kill_ports += f'Get-NetTCPConnection -LocalPort {p} -ErrorAction SilentlyContinue | ForEach-Object {{ Stop-Process -Id $_.OwningProcess -Force -ErrorAction SilentlyContinue }} ; '
            
            full_ps = f'{ps_kill_procs} ; {ps_kill_ports}'
            subprocess.run(['powershell', '-Command', full_ps], capture_output=True)
            logger(f" [OK] 已尝试清理进程: {', '.join(process_names)} 及端口: {target_ports}")
        else:
            # Linux/Mac 
            subprocess.run(["pkill", "-9", "-f", "node"], capture_output=True)
            subprocess.run(["pkill", "-9", "-f", "chrome"], capture_output=True)
            subprocess.run(["pkill", "-9", "-f", "msedge"], capture_output=True)
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
                    logger(f" [Action] 正在清理 Profile: {p_name}...")
                    success = False
                    for i in range(5):
                        try:
                            if sys.platform == "win32":
                                subprocess.run(['taskkill', '/F', '/IM', 'chrome.exe', '/T'], capture_output=True)
                                subprocess.run(['taskkill', '/F', '/IM', 'msedge.exe', '/T'], capture_output=True)
                                subprocess.run(['powershell', '-Command', f'Get-Process | Where-Object {{$_.Path -like "*{p_name}*"}} | Stop-Process -Force'], capture_output=True)
                            
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

