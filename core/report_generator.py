import os
import json
from datetime import datetime
from ai.llm_client import query_llm, get_current_token_usage
from core.utils import S_ERR, S_OK, S_INFO
import sys
import io

# 兼容 Windows 终端 Emoji 输出
if sys.platform == "win32" and isinstance(sys.stdout, io.TextIOWrapper):
    sys.stdout.reconfigure(encoding='utf-8')

class ReportGenerator:
    """
    自动化测试报告生成引擎
    负责将 Trace 交互轨迹转化为由 AI 总结的业务测试报告
    """
    @staticmethod
    def generate(trace, log_file=None, output_dir="artifacts/reports", logger=None):
        """
        生成完整的 Markdown 报告
        """
        log = logger if logger else print
        os.makedirs(output_dir, exist_ok=True)
        # 兼容处理 spec_id
        spec_id = "unknown"
        if hasattr(trace.metadata, 'spec_id'):
            spec_id = trace.metadata.spec_id
        elif isinstance(trace.metadata, dict):
            spec_id = trace.metadata.get('spec_id', 'unknown')

        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        report_filename = f"report_{spec_id}_{timestamp}.md"
        report_path = os.path.join(output_dir, report_filename)

        # 1. 提取核心统计数据
        metadata = trace.metadata
        m_url = getattr(metadata, 'url', None) or (metadata.get('url') if isinstance(metadata, dict) else "unknown")
        m_start = getattr(metadata, 'start_time', None) or (metadata.get('start_time') if isinstance(metadata, dict) else "unknown")
        
        test_result = trace.result
        r_status = getattr(test_result, 'status', 'unknown') or (test_result.get('status') if isinstance(test_result, dict) else 'unknown')
        r_conf = getattr(test_result, 'confidence', 0.0) or (test_result.get('confidence') if isinstance(test_result, dict) else 0.0)
        r_err = getattr(test_result, 'error_message', None) or (test_result.get('error_message') if isinstance(test_result, dict) else None)

        stats = {
            "test_name": m_url or spec_id,
            "status": r_status,
            "confidence": r_conf,
            "start_time": m_start,
            "end_time": datetime.now().isoformat(),
            "total_steps": len(trace.steps),
            "error_message": r_err,
            "token_stats": get_current_token_usage()
        }

        # 2. 构造 AI 总结提示词并获取总结
        log(f"  [Report] 正在请求 AI 总结测试业务要点 (URL: {m_url})...", flush=True)
        summary_content = ReportGenerator._get_ai_summary(trace, logger=log)

        # 3. 构造 Markdown 内容
        md_content = ReportGenerator._build_md(stats, summary_content, trace)

        # 4. 写入文件
        with open(report_path, 'w', encoding='utf-8') as f:
            f.write(md_content)
        
        log(f"  [Report] 报告生成成功: {report_path}", flush=True)
        return report_path

    @staticmethod
    def _get_ai_summary(trace, logger=None):
        """
        调用 LLM 对测试过程进行业务层面的总结
        """
        from ai.llm_client import _get_api_config
        api_key, _, _, _, _ = _get_api_config()
        log = logger if logger else print
        
        if not api_key:
            log("  [Report] [Skip] 未获取到 AI_API_KEY，跳过 AI 总结", flush=True)
            return "### ⚠️ AI 总结不可用\n(未配置 AI_API_KEY，仅提供原始数据)"

        mission_steps = []
        findings = []
        
        for i, step in enumerate(trace.steps, 1):
            s_instruction = getattr(step, 'instruction', 'Unknown') or (step.get('instruction') if isinstance(step, dict) else 'Unknown')
            s_verif = getattr(step, 'verification', None) or (step.get('verification') if isinstance(step, dict) else None)
            
            v_result = "unknown"
            v_reason = "No verification"
            if s_verif:
                v_result = getattr(s_verif, 'result', 'unknown') or (s_verif.get('result') if isinstance(s_verif, dict) else 'unknown')
                v_reason = getattr(s_verif, 'reason', 'unknown') or (s_verif.get('reason') if isinstance(s_verif, dict) else 'unknown')

            status_icon = "✅" if v_result == 'pass' else "❌"
            mission_steps.append(f"Step {i}: {s_instruction} -> {status_icon} {v_reason}")
            
            # 记录坏点 (Assert 失败)
            if v_result != 'pass':
                method_label = "业务拦截" if getattr(s_verif, 'method', '') == 'business_monitor' else "语义验证失败"
                findings.append(f"- {method_label}: 在执行 '{s_instruction}' 时发现问题，原因: {v_reason}")

        # [V3.3.12] 显式收集所有业务拦截告警作为高优先级上下文
        business_alerts = [f for f in findings if "业务拦截" in f]
        alert_context = "\n".join(business_alerts) if business_alerts else "未发现拦截告警"

        system_prompt = "你是一个专业的自动化测试分析师。请根据提供的测试步骤和验证结果，总结本次测试的‘测试要点’、‘执行结论’以及‘发现的问题’。使用中文，保持专业、精炼。"
        target_url = getattr(trace.metadata, 'url', 'unknown') or (trace.metadata.get('url') if isinstance(trace.metadata, dict) else 'unknown')
        
        user_prompt = f"""
测试目标: {target_url}
执行轨迹记录:
{chr(10).join(mission_steps)}

🚨 重点关注：业务级拦截告警 (必须在下方的“关键发现”中显式列出)：
{alert_context}

请基于以上原始数据，生成一个排版精美的总结报告片断。包含以下部分：
### 📝 测试要点总结
(总结本次测试覆盖了哪些业务功能点)

### 🔍 关键发现与坏点
(如果没有发现问题，请说明‘未发现明显业务异常’；如果有业务拦截告警，请将其加粗并置于首位描述)

### 💡 结论建议
(对系统健壮性的评价及后续建议)
"""
        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt}
        ]
        
        # 总结类任务是非关键动作，使用较短的超时(60s)和少量重试(2)，避免回放结束后死等
        summary = query_llm(messages, logger=log, timeout=60, max_retries=2)
        if summary.startswith("Error"):
            log(f"  {S_ERR} [Report] AI 总结失败: {summary}")
            return f"""
### ⚠️ AI 总结不可用
> [!WARNING]
> **API 调用失败**
> 
> **原因**: `{summary}`
> 
> **建议**: 
> 1. 检查 `.env` 中的 `AI_API_KEY` 是否有效。
> 2. 检查 `.env` 中的 `AI_PROXY` ({os.getenv("AI_PROXY", "未设置")}) 是否运行正常。
> 3. 检查 `.env` 中的 AI_MODEL=gemini-2.5-flash-lite ({os.getenv("AI_MODEL", "unknown")}) 名称是否正确。
"""
        return summary

    @staticmethod
    def _build_md(stats, ai_summary, trace):
        """
        组装最终的 Markdown 字符串
        """
        status_color = "green" if stats['status'] == 'pass' else "red"
        status_text = "通过 (PASS)" if stats['status'] == 'pass' else "失败 (FAIL)"
        
        template = f"""# 自动化测试执行报告

> [!NOTE]
> 本报告由 AI 测试引擎根据运行时真实轨迹自动生成。

## 📊 执行概览
- **测试名称**: {stats['test_name']}
- **执行结论**: <span style="color:{status_color};font-weight:bold;">{status_text}</span>
- **执行耗时**: {stats['start_time']} -> {stats['end_time']}
- **步骤总数**: {stats['total_steps']}
- **置信度**: {stats['confidence']}
{f"- **错误信息**: `{stats['error_message']}`" if stats['error_message'] else ""}
- **Token 消耗预期**: 准确计算 (Gemini API)

---

## 💰 Token 消耗统计
| 维度 | 消耗数量 (Tokens) |
| :--- | :--- |
| **输入 (Prompt)** | {stats['token_stats'].get('prompt', 0)} |
| **输出 (Completion)** | {stats['token_stats'].get('completion', 0)} |
| **思考 (Thoughts)** | {stats['token_stats'].get('thoughts', 0)} |
| **总计 (Total)** | {stats['token_stats'].get('total', 0)} |

---

{ai_summary}

---

## 📸 关键步骤回放图 (Selected)
"""
        # 提取有截图的步骤
        screenshots_section = ""
        for i, step in enumerate(trace.steps, 1):
            # 鲁棒提取 sub_actions
            sub_actions = getattr(step, 'sub_actions', []) or (step.get('sub_actions') if isinstance(step, dict) else [])
            for sub in sub_actions:
                s_action = getattr(sub, 'action', None) or (sub.get('action') if isinstance(sub, dict) else None)
                s_value = getattr(sub, 'value', None) or (sub.get('value') if isinstance(sub, dict) else None)
                
                if s_action == 'screenshot':
                   path = s_value
                   if path:
                       # 转换为相对路径以便在文档中引用
                       rel_path = path.replace('\\', '/')
                       screenshots_section += f"### 步骤 {i} 现场取证\n![Step {i} Screenshot](../../{rel_path})\n\n"
        
        if not screenshots_section:
            screenshots_section = "_（本次执行未触发自动截屏）_\n"

        template += screenshots_section
        
        template += "\n---\n*Report generated by AI Test Runner V3.1*"
        return template
