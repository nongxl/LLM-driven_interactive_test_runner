def get_system_guidance():
    """获取静态的系统指令和操作指南"""
    return (
        "▶ 你是一个专业、严谨的 UI 自动化测试助手。\n"
        "【核心任务】根据目标和当前页面 ARIA Tree，输出下一步的 JSON 操作指令。\n\n"
        "【输出规范】必须返回且仅返回纯 JSON 格式，例如: {\"action\": \"click\", \"target\": \"e1\"}\n\n"
        "【支持的操作类型】\n"
        "- goto: {\"action\": \"goto\", \"target\": \"URL\"}\n"
        "- click: {\"action\": \"click\", \"target\": \"eXX\"}\n"
        "- type: {\"action\": \"type\", \"target\": \"eXX\", \"value\": \"文本\"}\n"
        "- tab: {\"action\": \"tab\", \"target\": \"1\"} (切换页签，0为第一个)\n"
        "- snapshot: {\"action\": \"snapshot\"} (获取当前页面的实时 ARIA 快照)\n"
        "- scroll: {\"action\": \"scroll\", \"target\": \"eXX\"} (滚动到元素中心)\n"
        "- wait: {\"action\": \"wait\", \"value\": \"1000\"} (等待毫秒)\n"
        "- screenshot: {\"action\": \"screenshot\"} (保存页面截图)\n"
        "- keyboard: {\"action\": \"keyboard\", \"value\": \"Enter\"} (发送键盘按键)\n"
        "- assert: {\"action\": \"assert\", \"value\": \"预期描述\"} (进入下一步前的验证)\n"
        "注：支持所有 agent-browser 原生指令 (如 hover, drag 等)。\n\n"
        "【进阶准则】\n"
        "1. 每一个操作后，请务必使用 assert 确认状态后再进行下一步。\n"
        "2. 如果元素名称中包含长串无意义数字（如 0123456...），请忽略数字部分，重点匹配其包含的业务关键词。\n"
        "3. 如果元素无法定位，请尝试使用 snapshot 强制刷新或尝试其他属性。\n"
        "4. 【长流程循环能力】如果你的指令要求你遍历或执行多项子任务（如点击多个页签或处理多个模块），为了防止操作中断，每次返回 JSON 时请加上 `\"task_status\": \"in_progress\"`。系统将暂缓校验并再次向你请求下一步，直到你遍历完毕时输出 `{\"action\": \"assert\", \"value\": \"全部遍历完成\", \"task_status\": \"completed\"}` 来通知终止循环。\n"
        "5. 【数据严格性准则】严禁使用任何习惯性、经验性或默认的测试数据（例如：system_admin, 123456）。你必须且只能使用当前目标 (Target) 描述中明确提供的精确字符串。如果描述中未提供数据且页面需要输入，请输出询问或使用 assert 报错。数据准确性是 Trace 可回放性的生命线。\n"
    )

def init_step_messages(step):
    """初始化单步上下文消息列表"""
    system_instruction = get_system_guidance()
    messages = [
        {"role": "system", "content": system_instruction},
        {"role": "user", "content": f"▶ 目标: {step}\n\n执行策略：如果你发现动作报错或页面出现明显的异常提示（如 Toast、Alert、错误文字、Loading 超过 10s 不消失）：\n"
                                     "1. **影响分析**：该错误是否阻断了当前目标的达成？（例如：点击子系统链接后，URL 未变化且报‘系统无权限’，这就是阻断）。\n"
                                     "2. **决策处理**：如果是**业务阻断性错误**，必须立即输出带有错误描述的 `assert` 指令终止该步骤；如果是**非关键干扰**（如背景图标加载失败、统计 SDK 报错），则尝试重试、返回刷新或寻找其他路径，严禁无故跳过核心任务或在已知失败的情况下强行推进。只有全部符合要求时才最终输出并附带 `task_status: completed` 的 assert 结束指令。"}
    ]
    return messages

def append_snapshot(messages, snapshot):
    """将当前画面的 ARIA Tree 追加进会话作为最新状态感知"""
    aria_text = snapshot.get('aria_text', '').strip()
    global_alerts = snapshot.get('global_alerts', '').strip()

    content = ""
    if global_alerts:
        # [Enhancement] 强化异常信息的视觉感知，促使 LLM 关注非 ARIA 树内的业务报错
        content += (
            "🚨 [SYSTEM ALERT / BUSINESS ERROR DETECTED] 🚨\n"
            "--------------------------------------------------\n"
            f"Detected Messages: {global_alerts}\n"
            "--------------------------------------------------\n"
            "👉 请优先评估上述信息是否为“业务阻断（如无权限、加载失败、数据异常）”。\n"
            "如果是阻断性错误，请立即输出 assert 并附带详细错误原因终止当前步骤。\n\n"
        )

    if aria_text:
        content += f"▶ 最新页面结构视口 (ARIA Tree):\n{aria_text}"
    else:
        content += "▶ 最新页面结构: [空/加载中]"
    messages.append({"role": "user", "content": content})
