import os
import sys
import subprocess
import time
import math

# --- 终端颜色定义 ---
BLUE = "\033[94m"
GREEN = "\033[92m"
YELLOW = "\033[93m"
RED = "\033[91m"
BOLD = "\033[1m"
RESET = "\033[0m"

def clear_screen():
    os.system('cls' if os.name == 'nt' else 'clear')

def print_header(subtitle=None):
    print(f"{BLUE}{BOLD}")
    print("="*60)
    print("      🚀 LLM-driven Interactive Test Runner V3        ")
    if subtitle:
        print(f"      > {subtitle}")
    print("="*60)
    print(f"{RESET}")

def get_input(prompt, default=None):
    if default:
        res = input(f"{YELLOW}{prompt} (默认: {default}): {RESET}").strip()
        return res if res else default
    return input(f"{YELLOW}{prompt}: {RESET}").strip()

def select_file(directory, extensions=None, title="选择文件"):
    """
    通用分页文件选择器
    """
    if not os.path.exists(directory):
        print(f"{RED}❌ 目录不存在: {directory}{RESET}")
        time.sleep(1)
        return None

    files = []
    for f in os.listdir(directory):
        if extensions:
            if any(f.lower().endswith(ext) for ext in extensions):
                files.append(f)
        else:
            files.append(f)
    
    files.sort()
    
    if not files:
        print(f"{YELLOW}⚠️  目录 {directory} 下没有匹配的文件。{RESET}")
        time.sleep(1)
        return None

    page_size = 10
    current_page = 0
    total_pages = math.ceil(len(files) / page_size)

    while True:
        clear_screen()
        print_header(f"{title} (目录: {directory})")
        
        start_idx = current_page * page_size
        end_idx = min(start_idx + page_size, len(files))
        page_files = files[start_idx:end_idx]

        for i, f in enumerate(page_files, 1):
            print(f"  {BLUE}{i:2}.{RESET} {f}")

        print(f"\n--- 第 {current_page + 1} / {total_pages} 页 (共 {len(files)} 个文件) ---")
        print(f"{YELLOW}操作指南: 输入序号选中 | [n] 下一页 | [p] 上一页 | [q] 返回/取消{RESET}")
        
        choice = input(f"\n{BOLD}请输入选择: {RESET}").strip().lower()

        if choice == 'q':
            return None
        elif choice == 'n' and current_page < total_pages - 1:
            current_page += 1
        elif choice == 'p' and current_page > 0:
            current_page -= 1
        elif choice.isdigit():
            idx = int(choice)
            if 1 <= idx <= len(page_files):
                selected_file = page_files[idx - 1]
                return os.path.join(directory, selected_file)
            else:
                print(f"{RED}⚠️  无效序号，请重新选择。{RESET}")
                time.sleep(0.5)
        else:
            print(f"{RED}⚠️  无效输入。{RESET}")
            time.sleep(0.5)

def run_command(cmd_list, wait_at_end=True):
    print(f"\n{GREEN}[执行中] {BOLD}{' '.join(cmd_list)}{RESET}\n")
    success = False
    try:
        # 使用当前虚拟环境的 python
        python_exe = os.path.join(".venv", "Scripts", "python.exe") if os.name == 'nt' else "python3"
        if not os.path.exists(python_exe):
            python_exe = "python"
            
        cmd_list[0] = python_exe
        result = subprocess.run(cmd_list)
        success = (result.returncode == 0)
    except KeyboardInterrupt:
        print(f"\n{RED}[中断] 用户取消了执行。{RESET}")
    except Exception as e:
        print(f"\n{RED}[错误] 执行失败: {e}{RESET}")
    
    if wait_at_end:
        input(f"\n{BLUE}按回车键返回主菜单...{RESET}")
    return success

def menu_exploratory():
    print_header("1. 探索性测试 (Exploratory Test)")
    url = get_input("请输入被测网址 (URL)")
    if not url: return
    
    steps = get_input("探索步数 (Max Steps)", "30")
    
    print(f"\n{YELLOW}是否需要加载前置步骤 (YAML)?{RESET}")
    print("  1. 从 test_specs 选择")
    print("  2. 从 artifacts/smoke_tests 选择")
    print("  0. 跳过")
    sub_choice = input(f"{BOLD}请选择 (0-2): {RESET}").strip()
    
    pre_steps = None
    if sub_choice == '1':
        pre_steps = select_file("test_specs", [".yaml", ".yml"], "选择前置步骤")
    elif sub_choice == '2':
        pre_steps = select_file("artifacts/smoke_tests", [".yaml", ".yml"], "从 Smoke Tests 选择前置步骤")

    cmd = ["python", "runner/exploratory_runner.py", url, steps]
    if pre_steps:
        cmd.extend(["--pre-steps", pre_steps])
    
    run_command(cmd)

def menu_scripted():
    print_header("2. 定向脚本测试 (Scripted Test)")
    print(f"\n{YELLOW}从哪里加载测试脚本?{RESET}\n  1. test_specs (原始) | 2. smoke_tests (金牌)")
    sub_choice = input(f"{BOLD}请选择 (1-2): {RESET}").strip()
    
    dir_path = "artifacts/smoke_tests" if sub_choice == '2' else "test_specs"
    spec = select_file(dir_path, [".yaml", ".yml"], "选择业务脚本")
    if not spec: return
    
    pre_choice = input(f"\n{YELLOW}是否需要覆盖前置步骤? (0:跳过, 1:test_specs, 2:smoke_tests): {RESET}").strip()
    pre_steps = None
    if pre_choice in ['1', '2']:
        p_dir = "test_specs" if pre_choice == '1' else "artifacts/smoke_tests"
        pre_steps = select_file(p_dir, [".yaml", ".yml"], "选择前置步骤")
    
    cmd = ["python", "runner/test_runner.py", spec]
    if pre_steps: cmd.extend(["--pre-steps", pre_steps])
    run_command(cmd)

def menu_replay():
    print_header("3. 轨迹回放 (Trace Replay)")
    print(f"\n{YELLOW}加载 Trace 轨迹源:\n  1. traces/raw (录制) | 2. smoke_tests (金牌){RESET}")
    sub_choice = input(f"{BOLD}请选择 (1-2): {RESET}").strip()
    
    dir_path = "artifacts/smoke_tests" if sub_choice == '2' else "artifacts/traces/raw"
    trace = select_file(dir_path, [".json"], "选择轨迹文件")
    if not trace: return
    
    strict = get_input("是否开启严格模式? (y/n)", "n")
    cmd = ["python", "tracer/replay_runner.py", trace]
    if strict.lower() == 'y': cmd.append("--strict")
    run_command(cmd)

def menu_batch():
    """批量测试引擎"""
    print_header("6. 自动化批量测试 (Batch Execution)")
    print(f" {BOLD}请选择批量任务类型：{RESET}")
    print(f"  {BLUE}1.{RESET} 批量运行脚本 (Running all YAML in directory)")
    print(f"  {BLUE}2.{RESET} 批量回放轨迹 (Replaying all JSON in directory)")
    print(f"  {RED}0.{RESET} 返回")
    
    choice = input(f"\n{BOLD}输入编号 (0-2): {RESET}").strip()
    if choice == '0': return

    # 选择目录
    print(f"\n{YELLOW}请选择目标目录：{RESET}")
    print("  1. artifacts/smoke_tests (金牌库)")
    print("  2. test_specs (脚本库)")
    print("  3. artifacts/traces/raw (录制轨迹库)")
    dir_choice = input(f"{BOLD}请输入 (1-3): {RESET}").strip()
    
    target_dir = "artifacts/smoke_tests"
    if dir_choice == '2': target_dir = "test_specs"
    elif dir_choice == '3': target_dir = "artifacts/traces/raw"

    ext = ".yaml" if choice == '1' else ".json"
    files = [f for f in os.listdir(target_dir) if f.lower().endswith(ext)]
    files.sort()

    if not files:
        print(f"{RED}❌ 目录 {target_dir} 下没有类型为 {ext} 的文件。{RESET}")
        time.sleep(1)
        return

    # [NEW] 批量脚本测试支持全局 pre-steps
    batch_pre_steps = None
    if choice == '1':
        print(f"\n{YELLOW}是否为该批次所有脚本注入全局前置步骤 (YAML)?{RESET}")
        print("  1. 从 test_specs 选择")
        print("  2. 从 artifacts/smoke_tests 选择")
        print("  0. 跳过 (使用各脚本内定义的或无前置)")
        p_choice = input(f"{BOLD}请选择 (0-2): {RESET}").strip()
        if p_choice in ['1', '2']:
            p_dir = "test_specs" if p_choice == '1' else "artifacts/smoke_tests"
            batch_pre_steps = select_file(p_dir, [".yaml", ".yml"], "选择全局前置步骤")

    print(f"\n{GREEN}即将批量运行 {len(files)} 个任务...{RESET}")
    time.sleep(1)

    results = []
    for f in files:
        f_path = os.path.join(target_dir, f)
        print(f"\n{BLUE}{'='*60}{RESET}")
        print(f"正在执行任务: {BOLD}{f}{RESET}")
        print(f"{BLUE}{'='*60}{RESET}")
        
        cmd = ["python"]
        if choice == '1': 
            cmd.extend(["runner/test_runner.py", f_path])
            if batch_pre_steps:
                cmd.extend(["--pre-steps", batch_pre_steps])
        else: 
            cmd.extend(["tracer/replay_runner.py", f_path])
        
        success = run_command(cmd, wait_at_end=False)
        results.append((f, "PASS" if success else "FAIL"))

    # 打印汇总报告
    clear_screen()
    print_header("批量执行报告 (Batch Report)")
    print(f"{BOLD}{'文件名':<40} {'状态':<10}{RESET}")
    print("-" * 55)
    pass_count = 0
    for name, status in results:
        color = GREEN if status == "PASS" else RED
        print(f"{name:<40} {color}{status}{RESET}")
        if status == "PASS": pass_count += 1
    
    print("-" * 55)
    total = len(results)
    print(f"{BOLD}总计: {total} | 成功: {GREEN}{pass_count}{RESET} | 失败: {RED}{total - pass_count}{RESET}")
    input(f"\n{BLUE}按回车键返回主菜单...{RESET}")

def menu_analyser():
    print_header("4. 轨迹聚类与分析 (Trace Analysis)")
    # ... 原逻辑 ...
    run_command(["python", "runner/trace_analyser.py", "--dir", "artifacts/traces/raw", "--output", "artifacts/smoke_tests"])

def menu_cleanup():
    print_header("5. 环境清理 (Cleanup Environment)")
    from core.utils import cleanup_browser_env
    cleanup_browser_env()
    input(f"\n{GREEN}[OK] 清理完成。按回车键返回...{RESET}")

def main():
    while True:
        clear_screen()
        print_header("主菜单")
        print(f" {BOLD}请选择功能：{RESET}")
        print(f"  {BLUE}1.{RESET} 探索性测试 (Exploratory Test)")
        print(f"  {BLUE}2.{RESET} 定向脚本测试 (Scripted Test)")
        print(f"  {BLUE}3.{RESET} 轨迹回放 (Trace Replay)")
        print(f"  {BLUE}4.{RESET} 轨迹聚类与分析 (Trace Analysis)")
        print(f"  {BLUE}5.{RESET} 环境清理 (Cleanup)")
        print(f"  {BLUE}6.{RESET} {BOLD}自动化批量测试 (Batch Test){RESET}")
        print(f"  {RED}0.{RESET} 退出 (Exit)")
        print()
        
        choice = input(f"{BOLD}输入编号 (0-6): {RESET}").strip()
        if choice == '1': menu_exploratory()
        elif choice == '2': menu_scripted()
        elif choice == '3': menu_replay()
        elif choice == '4': menu_analyser()
        elif choice == '5': menu_cleanup()
        elif choice == '6': menu_batch()
        elif choice == '0': break
        else: time.sleep(1)

if __name__ == "__main__":
    main()
