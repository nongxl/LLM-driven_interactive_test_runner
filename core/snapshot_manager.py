import asyncio
import json
import os
import time
import uuid

# [v1.8 优化A] 增量扫描：追踪上次执行全谱业务异常扫描时的页面 URL
_last_scanned_url: str = ""

def _project_root():
    """返回项目根目录（package.json 所在位置）"""
    return os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))

def refine_aria_tree(aria_text: str) -> str:
    """
    语义清洗引擎：精简 agent-browser 的原生快照，剔除视觉噪音。
    """
    if not aria_text: return ""
    
    lines = aria_text.split('\n')
    refined = []
    
    # 垃圾节点规则：图标、装饰性元素、无意义容器
    noise_keywords = ["svg", "path", "symbol", "defs", "mask", "clippath", "g "]
    
    for line in lines:
        lower_line = line.lower().strip()
        
        # 1. 剔除明确的装饰性图形节点
        if any(kw in lower_line for kw in noise_keywords):
            continue
            
        # 2. 剔除没有任何内容的 generic/None 容器
        # 匹配模式：- generic "" [ref=eXX] 或 - None "" [ref=eXX]
        if ' "" ' in line and ('- generic' in line or '- None' in line):
            # 除非是顶级节点（缩进为0），否则认为它是无意义的中间层
            if not line.startswith("-"):
                continue
                
        refined.append(line)
        
    return "\n".join(refined)

async def get_snapshot(logger=None, target_url=None):
    """
    异步获取页面快照，确保 Ref ID 的全局唯一性与语义精简。
    """
    from core.action_executor import execute as execute_action
    
    def log(msg):
        msg_str = str(msg)
        is_debug = "DEBUG:" in msg_str.upper() or (msg_str.startswith(" [") and not msg_str.startswith(" [Wait]"))
        show_debug = os.environ.get("TEST_DEBUG") == "1"
        if is_debug and not show_debug: return
        
        if "DEBUG:" not in msg_str.upper() and not msg_str.startswith(" ["):
            msg_str = f"DEBUG: {msg_str}"
            
        if logger: logger(msg_str)
        else: print(msg_str, flush=True)

    # 1. 准备环境与智能等待
    current_page_url = target_url
    global_alerts = ""

    try:
        # [Wait Logic] 利用 Playwright 进行高性能等待与扫描
        from core.verification_engine import get_playwright_page
        page = await get_playwright_page(target_url=current_page_url, logger=logger)
        
        if page:
            # 执行智能载入判定 JS
            js_wait_script = """(() => {
                function isPageLoading() {
                   if (document.readyState !== 'complete' && document.readyState !== 'interactive') return true;
                   const loadingSelectors = ['.ant-spin', '.el-loading-mask', '.loading-wrp', '#loading', '.ant-skeleton'];
                   for (let s of loadingSelectors) {
                       const el = document.querySelector(s);
                       if (el && window.getComputedStyle(el).display !== 'none') return true;
                   }
                   if (!document.body || document.body.children.length === 0) return true;
                   return false;
                }
                return isPageLoading();
            })()"""
            
            for i in range(5):
                try:
                    is_loading = await asyncio.wait_for(page.evaluate(js_wait_script), timeout=3.0)
                    if not is_loading: break
                    log(f" [Wait] 页面正在加载中 ({i+1}/5)...")
                    await asyncio.sleep(1.5)
                except: break

            # [Alert Logic] 同步获取对话框消息
            from core.verification_engine import get_last_dialog_message
            global_alerts = get_last_dialog_message() or ""

        # 2. 核心快照获取 (唯一真理来源: ActionExecutor)
        log("正在通过 Agent Browser 引擎抓取实时快照...")
        raw_res_str = await execute_action({"action": "snapshot"})
        
        # 解析引擎输出
        # 初始化默认结果
        res = {
            "aria_text": "Error: Snapshot failed",
            "url": current_page_url or "",
            "refs": {},
            "global_alerts": global_alerts
        }

        try:
            # 找到 JSON 部分
            json_start = raw_res_str.find("{")
            json_end = raw_res_str.rfind("}") + 1
            if json_start >= 0:
                data = json.loads(raw_res_str[json_start:json_end])
                
                # 提取核心数据
                raw_aria = data.get("data", {}).get("snapshot", "")
                refined_aria = refine_aria_tree(raw_aria)
                
                # 优先级抓取 URL: Data > Page.url > current_page_url
                detected_url = data.get("data", {}).get("url")
                if not detected_url and page:
                    try: detected_url = page.url
                    except: pass
                if not detected_url: detected_url = current_page_url or ""

                # 注入业务异常信息
                if global_alerts:
                    refined_aria = f"--- 页面业务异常探测 ---\nDetected Alerts: {global_alerts}\n--------------------------\n" + refined_aria
                
                res["aria_text"] = refined_aria
                res["url"] = detected_url
                res["refs"] = data.get("data", {}).get("refs", {})
               
                node_count = refined_aria.count("[ref=")
                log(f" [OK] 语义快照获取成功 (Nodes: {node_count}, URL: {res['url']})")
            else:
                log(f" [Error] 引擎输出未包含合法 JSON: {raw_res_str[:100]}...")
        except Exception as ee:
            log(f" [Error] 解析引擎快照失败: {ee}")

        return res

    except Exception as ge:
        log(f" [Critical] 快照全流程异常: {ge}")

    return {"aria_text": "", "url": current_page_url or "", "refs": {}, "global_alerts": global_alerts}

def parse_aria_tree(ax_tree):
    """
    (保留原有 Native 树解析逻辑的独立导出，若需要)
    """
    return "" # 实际逻辑已在 get_snapshot 内部闭包实现
