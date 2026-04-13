import asyncio
import json
import os
import time
import uuid
import datetime

# [V3.3.2] 异常持久化缓冲区，用于暂存步骤中段捕获的瞬时报错
_ALERTS_BUFFER = []

def clear_alerts_buffer():
    global _ALERTS_BUFFER
    _ALERTS_BUFFER = []

def add_alert_to_buffer(msg: str):
    """
    [V3.3.5] 提供统一的异常上报接口，允许网络监控等外部模块写入异常
    """
    if not msg:
        return
    global _ALERTS_BUFFER
    if msg not in _ALERTS_BUFFER:
        _ALERTS_BUFFER.append(msg)

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

async def detect_business_errors(page, logger=None) -> str:
    """
    [V3.3] 深度业务异常探测引擎
    针对 Toast、业务报错、数据库错误等进行全量 DOM 扫描
    """
    if not page: return ""
    
    # 获取环境变量中的关键字，若无则使用默认值
    keywords_env = os.environ.get("ERROR_KEYWORDS", "数据库操作失败,网络异常,权限不足,系统繁忙,未知错误,Exception")
    keywords = [k.strip() for k in keywords_env.split(",") if k.strip()]
    
    # 注入扫描脚本 (增强版：支持递归扫描 iframe 和 Shadow Root)
    js_detect_script = """(keywords) => {
        const results = [];
        const seen = new Set();

        function scanNode(doc) {
            if (!doc || seen.has(doc)) return;
            seen.add(doc);

            // 1. 扫描常见的 Toast/Message 容器 (AntD, Element, etc.)
            const toastSelectors = [
                '.ant-message-notice', '.ant-notification-notice', 
                '.el-message', '.el-notification', 
                '.v-toast', '.toast', '.alert-danger', '.alert-error'
            ];
            
            toastSelectors.forEach(s => {
                try {
                    doc.querySelectorAll(s).forEach(el => {
                        if (el.innerText && (el.offsetParent !== null || el.getClientRects().length > 0)) {
                            results.push(`[Toast/Alert] ${el.innerText.trim()}`);
                        }
                    });
                } catch(e) {}
            });

            // 2. 关键字全量扫描
            try {
                const body = doc.body || doc;
                const allText = (body.innerText || "") + " " + (body.textContent || "");
                for (let k of keywords) {
                    if (allText.includes(k)) {
                        // 1. 优先寻找单一文本节点 (高精度匹配)
                        const walker = doc.createTreeWalker(body, NodeFilter.SHOW_TEXT, null, false);
                        let node;
                        let foundInNode = false;
                        while(node = walker.nextNode()) {
                            if (node.textContent.includes(k)) {
                                results.push(`[Keyword Match] ${k}: ${node.parentElement.innerText.substring(0, 100)}`);
                                foundInNode = true;
                                break; 
                            }
                        }

                        // 2. [V3.3.6 增强] 分段文本回退匹配 (解决关键词被 <span> 拆分的问题)
                        if (!foundInNode) {
                            try {
                                const findDeepestContainer = (root) => {
                                    if (!root || !root.children) return null;
                                    for (let child of root.children) {
                                        if (child.innerText && child.innerText.includes(k)) {
                                            const deeper = findDeepestContainer(child);
                                            return deeper || child;
                                        }
                                    }
                                    return null;
                                };
                                const container = findDeepestContainer(body);
                                if (container) {
                                    results.push(`[Fragmented Match] ${k}: ${container.innerText.substring(0, 100)}`);
                                } else {
                                    results.push(`[Fuzzy Match] ${k} detected in page text.`);
                                }
                            } catch(e) {}
                        }
                    }
                }
            } catch(e) {}

            // 3. 递归扫描 iframe
            try {
                const iframes = doc.querySelectorAll('iframe, frame');
                iframes.forEach(iframe => {
                    try {
                        scanNode(iframe.contentDocument || iframe.contentWindow.document);
                    } catch(e) {
                        // 跨域 iframe 无法扫描，忽略
                    }
                });
            } catch(e) {}
            
            // 4. 尝试扫描 Shadow Roots (针对现代组件库)
            // [V3.3.6 优化] 仅针对疑似包含组件的节点进行启发式扫描，降低全量 * 遍历压力
            try {
                const hosts = doc.querySelectorAll('*'); // 在 doc 范围内查找
                for (let i = 0; i < hosts.length; i++) {
                    const el = hosts[i];
                    if (el.shadowRoot) {
                        scanNode(el.shadowRoot);
                    }
                }
            } catch(e) {}
        }

        scanNode(document);
        return Array.from(new Set(results)).join(" | ");
    }"""
    
    try:
        # 增加 2s 超时执行，防止阻塞
        found_errors = await asyncio.wait_for(page.evaluate(js_detect_script, keywords), timeout=2.0)
        
        if found_errors and logger:
            # [V3.3.2] 这里不使用 log() 辅助器，因为它会被 is_debug 规则过滤
            # 我们希望在开发/复现阶段，捕捉到异常时强制输出提示
            logger(f"  [Found] 业务异常监测成功: {found_errors}")
                
        return found_errors if found_errors else ""
    except Exception as e:
        if os.environ.get("TEST_DEBUG") == "1" and logger:
            logger(f"  [DEBUG] 业务异常探测评估失败: {e}")
        return ""
async def check_business_errors(page, logger=None):
    """
    [V3.3.2] 极轻量级扫描入口，供脉冲式监控使用
    """
    if not page: return ""
    errs = await detect_business_errors(page, logger=logger)
    if errs:
        global _ALERTS_BUFFER
        if errs not in _ALERTS_BUFFER:
            _ALERTS_BUFFER.append(errs)
    return errs

async def active_wait_and_monitor(seconds, page, logger=None):
    """
    [V3.3.2] 主动监控式等待：在等待期间每隔 500ms 扫描一次业务异常
    """
    if not page:
        await asyncio.sleep(seconds)
        return
    
    start_time = time.time()
    if logger:
        logger(f"  [Wait] 主动监控已启动 (Duration: {seconds}s, Interval: 0.25s)")
        
    while time.time() - start_time < seconds:
        # 执行轻量级扫描
        errs = await check_business_errors(page, logger=logger)
        if errs and logger:
            # 同样使用强制输出，不走 log() 辅助器的过滤
            logger(f"  [Monitor] 捕捉到脉冲异常: {errs}")
            
        # [V3.3.2 优化] 将脉冲频率提升至 250ms，确保捕捉 sub-second 的 Toast
        await asyncio.sleep(0.25)

async def get_snapshot(logger=None, target_url=None):
    """
    异步获取页面快照，确保 Ref ID 的全局唯一性与语义精简。
    """
    from core.action_executor import execute as execute_action
    
    def log(msg):
        msg_str = str(msg)
        is_debug = "DEBUG:" in msg_str.upper() or (msg_str.startswith(" [") and not any(k in msg_str for k in (" [Wait]", " [Alert]", " [Found]", " [Monitor]")))
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

            # [V3.3.2 Early-Detection] 在等待加载前先抢先扫描一轮，抓住立即出现的 Toast
            early_business_errors = await detect_business_errors(page, logger=logger)
            if early_business_errors:
                _ALERTS_BUFFER.append(early_business_errors)

            # [Alert Logic] 同步获取对话框消息
            from core.verification_engine import get_last_dialog_message
            native_alerts = get_last_dialog_message() or ""
            
            # [V3.3.2 Post-Scan] 加载完成后再扫一轮
            late_business_errors = await detect_business_errors(page, logger=logger)
            if late_business_errors:
                _ALERTS_BUFFER.append(late_business_errors)
            
            # 合并缓冲区中的所有异常 (去重后拼接)
            unique_alerts = list(dict.fromkeys(_ALERTS_BUFFER))
            if native_alerts and f"Native: {native_alerts}" not in unique_alerts:
                unique_alerts.insert(0, f"Native: {native_alerts}")
            
            global_alerts = " | ".join(unique_alerts)
            
            # 标记：一旦 snapshot 过程消耗了 Buffer，建议在 runner 层外部清理，或此处自动清理
            # 我们选择在 Runner 的步骤开始时显示调用 clear_alerts_buffer

        # 2. 核心快照获取 (唯一真理来源: ActionExecutor)
        raw_res_str = await execute_action({"action": "snapshot"})
        
        # 解析引擎输出
        res = {
            "aria_text": "Error: Snapshot failed",
            "url": current_page_url or "",
            "refs": {},
            "global_alerts": global_alerts
        }

        try:
            json_start = raw_res_str.find("{")
            json_end = raw_res_str.rfind("}") + 1
            if json_start >= 0:
                data = json.loads(raw_res_str[json_start:json_end])
                
                raw_aria = data.get("data", {}).get("snapshot", "")
                refined_aria = refine_aria_tree(raw_aria)
                
                detected_url = data.get("data", {}).get("url")
                if not detected_url and page:
                    try: detected_url = page.url
                    except: pass
                if not detected_url: detected_url = current_page_url or ""

                # 注入业务异常信息到 ARIA 树头部，确保所有 Runner 和 LLM 都能感知
                if global_alerts:
                    log(f" [Alert] 捕捉到业务异常: {global_alerts}")
                    refined_aria = f"--- [BUSINESS EXCEPTION DETECTED] ---\n{global_alerts}\n--------------------------\n" + refined_aria
                
                res["aria_text"] = refined_aria
                res["url"] = detected_url
                res["refs"] = data.get("data", {}).get("refs", {})
                res["hash"] = data.get("data", {}).get("hash", str(uuid.uuid4())[:8])
               
                node_count = refined_aria.count("[ref=")
                log(f" [OK] 快照获取成功 (Nodes: {node_count}, URL: {res['url']})")
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
