def get_system_guidance():
    """获取静态的系统指令和操作指南"""
    return (
        "▶ 你是一个专业、严谨的 UI 自动化测试助手。\n"
        "【核心任务】根据目标和当前页面 ARIA Tree，输出下一步的 JSON 操作指令。\n\n"
        "【思维链准则 (Thinking Chain)】\n"
        "在给出最终 JSON 之前，请务必进行详尽的逻辑推演（如果你使用的是具备独立思考能力的模型，请在思考区完成；否则请在心中默念并在最终输出前简述）：\n"
        "1. 页面现状分析：当前处于什么页面？有没有业务报错（Alert/Toast）？\n"
        "2. 目标解构：当前目标是什么？为了达成目标还需要哪几个关键步骤？\n"
        "3. 动作决策：在当前页面结构中，哪个 ref 对应的元素是实现下一步的最优解？为什么？\n\n"
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
        "4. 【长流程循环与全量遍历】如果你的指令要求你遍历或执行多项子任务（如点击‘所有’链接、处理‘列表’中每一项），为了防止操作中断，每次返回 JSON 时请加上 `\"task_status\": \"in_progress\"`。你必须逐一处理完当前页面乃至后续翻页中的**每一项**，严禁在待处理项未清空前自行断言 `completed`。只有当确定所有符合描述的入口或数据多页全部处理完毕时，方可输出 `{\"action\": \"assert\", \"value\": \"全部遍历完成\", \"task_status\": \"completed\"}` 来通知终止循环。\n"
        "5. 【错误收集策略】遇到‘无权限’、‘数据异常’等业务报错时，不要直接终止整个脚本。你应该：1. 输出 assert 记录当前节点失败；2. 关闭报错页签或返回主列表；3. 继续处理列表中的下一项。我们的目标是尽可能收集系统中所有的异常点，而非遇错即停。\n"
        "6. 【绝对数据严格性准则】严禁使用任何习惯性数据（如 system_admin, 123456, password, Admin@2024 等）。你必须 100% 忠实于指令描述中提供的**原始字面量**。严禁自行添加大小写转换、符号后缀或任何形式的‘修饰’。必须记住：指令中写的是什么，输入框里就必须是什么。错误的数据输入会导致 Trace 采集彻底失效。\n"
    )

def init_step_messages(step):
    """初始化单步上下文消息列表"""
    system_instruction = get_system_guidance()
    messages = [
        {"role": "system", "content": system_instruction},
        {"role": "user", "content": f"▶ 目标: {step}\n\n"
                                     "🚨 [核心数据约束] 🚨\n"
                                     "严禁自行生成的测试数据。你必须 100% 忠实于上方目标中用引号标识或明确提及的字面量。\n"
                                     "禁止输入 `Admin@2024`, `password`, `123456` 等任何你‘觉得’像密码的东西。\n\n"
                                     "执行策略：如果你发现动作报错或页面出现明显的异常提示（如 Toast、Alert、错误文字、Loading 超过 10s 不消失）：\n"
                                     "1. **影响分析**：该错误是否阻断了当前目标的达成？（例如：点击子系统链接后，报‘系统无权限’，这就是业务阻断）。\n"
                                     "2. **决策处理**：如果是**业务阻断性错误**，必须立即输出带有错误描述的 `assert` 指令记录该失败点（此时系统会自动保存截屏凭证）。**重点**：记录后不要停止脚本，应寻求返回上一级或处理列表下一项的路径，直到所有项遍历完毕。严禁无故跳过核心任务。"}
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
