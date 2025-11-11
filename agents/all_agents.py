# all_agent.py
import asyncio, os
from oxygent import MAS, oxy,Config,preset_tools
import re
from oxygent.schemas.oxy import OxyRequest, OxyResponse, OxyState
import dotenv
from pydantic import BaseModel, Field
from typing import List, Union
from oxygent.utils.llm_pydantic_parser import PydanticOutputParser # 导入解析器
import json
import sys
from typing import Any, List, Optional, Type, Union
import dashscope # <--- 1. 添加 DashScope
from dashscope import MultiModalConversation # <--- 2. 添加 MultiModalConversation
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__))) 

# 定义截图保存的根目录 (例如 E:/MetaJD/web/screenshots)
SCREENSHOT_DIR_BASE = os.path.join(PROJECT_ROOT, "web", "screenshots")
os.makedirs(SCREENSHOT_DIR_BASE, exist_ok=True)

executor_subagents_name = [#执行器可用的子代理列表
    "python_agent",
    "file_agent",
    "math_agent",
    "string_agent",
    "system_check_agent",
    "firecrawl_agent",
    "github_agent",
    "multimodal_agent",
    "stock_agent",
    "visual_browser_workflow_agent",
    "search_agent",
    "song_recognition_agent"
]
def update_query(oxy_request: OxyRequest):
    user_query = oxy_request.get_query(master_level=True)
    current_query = oxy_request.get_query()
    oxy_request.set_query(
        f"user query is {user_query}\ncurrent query is {current_query}"
    )
    return oxy_request


def extract_json_block(text: str) -> Optional[str]:
    """
    从可能包含额外字符的文本中提取第一个（最外层）JSON对象。
    """
    # 寻找第一个 '{' 和最后一个 '}'
    match = re.search(r"\{.*\S.*\}", text, re.DOTALL)
    if match:
        return match.group(0)
    return None

async def plan_and_solve_workflow(oxy_request: OxyRequest) -> OxyResponse:
    """
    手动实现的规划-执行-反思工作流。
    """
    original_query = oxy_request.get_query()
    max_replan_rounds = 8 # 限制循环次数
    
    # 步骤 1: 初始规划 (调用 planner)
    planner_query = plan_parser.format(original_query)
    planner_response = await oxy_request.call(
        callee="planner", 
        arguments={"query": planner_query}
    )
    
    try:
        # 先提取，再解析
        json_string = extract_json_block(planner_response.output)
        if not json_string:
            raise Exception("LLM 返回的响应中未找到 JSON。")
        plan_data = plan_parser.parse(json_string)
        plan_steps = plan_data.steps
    except Exception as e:
        # 如果规划失败，直接返回错误
        return OxyResponse(
            state=OxyState.FAILED,
            output=f"规划 Agent 返回格式错误或规划失败: {e}\n原始输出: {planner_response.output}"
        )
        
    past_steps = ""
    
    # 步骤 2: 循环执行与重规划
    for current_round in range(max_replan_rounds):
        if not plan_steps:
            break 
            
        task = plan_steps[0]
        
        # 2.1 执行当前步骤 (调用 executor)
        task_formatted = task
        executor_response = await oxy_request.call(
            callee="executor", 
            arguments={"query": task_formatted}
        )
        
        # 2.2 更新历史
        past_steps += f"\nTask: {task}, Result: {executor_response.output}"
        
        is_final_step_completed = (
    isinstance(plan_steps, (list, tuple)) and len(plan_steps) <= 1
)
        last_task_executed = task
        last_task_result = executor_response.output
        # 2.3 重规划/反思 (如果启用)
        replan_query = f"""
        ## 1. Original Objective {original_query} 
        ## 2. Latest History (Just Executed) 
        # - **Task:** {last_task_executed} 
        # - **Result:** {last_task_result} 
        ## 3. Remaining Plan {plan_steps[1:]} 
        ## YOUR JOB: CRITIQUE and DECIDE You must strictly follow this reflection process: 
        **Step A: Critique** 
        1. Compare "Task" vs. "Result": * Did the "Result" successfully complete the "Task"? * (e.g., If "Task" was "find official URL", is the "Result" a plausible official URL?) 
        2. Compare "Result" vs. "Original Objective": * Is this "Result" (even if it completed the task) helpful for achieving the "Original Objective"? * (e.g., If "Objective" is about a specific company, is the "Result" from a relevant source?) 
        **Step B: Decide** 
        1. **If Critique FAILED (Result is irrelevant, wrong, or an error):** 
        Your job is to **flexibly** generate a **new, corrective plan** (of one or more steps) that logically resolves the specific error shown in the 'Result'.
        **Default behavior:** Fix the problem *locally* — create corrective step(s) that address the error, then **append** the original `3. Remaining Plan` afterward.
        **However**, if you determine that the current plan is no longer valid or too broken to repair logically,  
         you **may fully restart** the plan from the beginning — but only if this clearly helps achieve the *Original Objective* more efficiently or accurately.
        
        2. **If Critique SUCCEEDED and the "Original Objective" is now met:** 
        **Use the Response action** and extract the final answer from the history. 
        3. **If Critique SUCCEEDED but the "Original Objective" is NOT yet met:**
        * Continue with the "Remaining Plan".
        * (Optional: Inject context from the "Result" into the next step if needed). * 
        **Use the Plan action to return the *updated remaining* plan.** 
        """
        if is_final_step_completed:
             replan_query += (
                 "\n\n**CRITICAL INSTRUCTION FOR FINAL RESPONSE:** "
                 "Based *only* on the '执行历史', extract the precise final answer to the '原始用户目标'. "
                 "The answer MUST use the same language as the user query, unless the user explicitly requests output in another language.Note: If the user only asks to use English punctuation, that does not mean the output should be in English."
                 "Do **NOT** add any extra words, prefixes, or context not present in the extracted result."
                 "The 'response' field in the 'Response' action should contain ONLY this exact extracted answer."
             )
        replan_query_formatted = action_parser.format(replan_query) # 使用 Action 解析器
        
        replanner_response = await oxy_request.call(
            callee="planner", #  关键：使用 planner Agent 兼任重规划
            arguments={"query": replan_query_formatted}# type: ignore #
        )
        
        try:
            # 先提取，再解析
            json_string = extract_json_block(replanner_response.output)
            if not json_string:
                # (如果找不到 JSON，将输出视为错误文本)
                raise Exception(f"LLM 未返回 JSON 计划。返回内容: {replanner_response.output}")
            action_data = action_parser.parse(json_string)
        except Exception as e:
            # (关键修正：不要在 output 中返回 replanner_response.output)
            return OxyResponse( 
            state=OxyState.FAILED,
            output=f"重规划 Agent 返回格式错误: {e}"
            )
        # 2.4 决策：响应或继续规划
        if hasattr(action_data.action, "response"):
            # 最终答案
            return OxyResponse(
                state=OxyState.COMPLETED,
                output=action_data.action.response
                )
        else:
            # 新计划
            plan_steps = action_data.action.steps
            
    # 步骤 3: 总结 (如果循环提前结束但没有返回答案)
    summary_query = f"The task was: {original_query}. Final execution history:\n{past_steps}. Please provide the final, exact answer."
    summary_response = await oxy_request.call(
        callee=LLM_MODEL, 
        arguments={"query": summary_query}
    )
    
    return summary_response
# (在 all_agents.py 中，用这个函数替换 vlm_loader_workflow)

async def vlm_loader_workflow(oxy_request: OxyRequest) -> OxyResponse:
    """
    工作流 (VLM Loader v12)：
    1.  提取文本查询。
    2.  提取文件名 (pdf, jpg, png, mp4, mp3)。
    3.  调用 file_agent 查找文件路径。
    4.  分析文件类型：
        a. PDF / MP4 -> 转换为图像 -> 调用 VLM。
        b. 图像 -> 直接调用 VLM。
        c. MP3 -> 调用 audio_vlm_agent。
    """
    content_list = []
    vlm_messages = []
    # --- 1. 提取文本查询 
    query_input = oxy_request.get_query()
    master_query = oxy_request.get_query(master_level=True)
    text_query = "" 
    if isinstance(query_input, str): text_query = query_input
    elif isinstance(query_input, list):
        for part in query_input:
            try:
                if part.get('type') == 'text' and 'text' in part: text_query = part['text']; break
                elif part.get('part', {}).get('content_type') == 'text/plain': text_query = part['part']['data']; break
            except (AttributeError, TypeError): continue
    if not text_query: return OxyResponse(state=OxyState.FAILED, output=f"VLM工作流错误：在查询中未找到文本内容 (Query: {query_input})")

    # --- 2. 提取文件名 ---
    filename_match = re.search(r"['\"]?([\w\-\.]+\.(pdf|jpg|png|jpeg|mp4|mp3))['\"]?", text_query, re.IGNORECASE)
    if not filename_match: return OxyResponse(state=OxyState.FAILED, output=f"VLM工作流错误：在查询 '{text_query}' 中未找到有效的文件名 (e.g., pdf, jpg, mp4, mp3)。")
    filename = filename_match.group(1)
    file_ext = filename.split('.')[-1].lower()

    # --- 3. 查找文件路径 ---
    find_file_query = f"请递归查找文件 '{filename}' 并返回第一个匹配的绝对路径"
    find_resp = await oxy_request.call(callee="file_agent", arguments={"query": find_file_query})
    
    # --- 4. 解析文件路径 (正确) ---
    file_path = ""
    output_str = "" 
    if isinstance(find_resp.output, list):
        if len(find_resp.output) > 0: output_str = str(find_resp.output[0])
        else: return OxyResponse(state=OxyState.COMPLETED, output=f"文件 '{filename}' 未找到 (file_agent 返回了空列表)。")
    elif isinstance(find_resp.output, str): output_str = find_resp.output
    else: return OxyResponse(state=OxyState.FAILED, output=f"file_agent 返回了意外的类型: {type(find_resp.output)}")
    
    path_match = re.search(r"([A-Za-z]:\\[^\]\s,\"\*`]+)|(/[^\]\s,\"\*`]+)", output_str) # <--- 在 [^...] 中添加了 `
    
    if path_match:
        file_path = path_match.group(0).strip("'\"`* ") # <--- (同时加强 strip)
    else:
         return OxyResponse(
            state=OxyState.COMPLETED,
            output=f"文件 '{filename}' 未找到 (在 '{output_str}' 中解析路径失败)。"
        )
    # --- 5. 根据文件类型处理 ---

    if file_ext == 'mp3':
        
        
        combined_query = f"""
        User Query: {text_query}
        File Path: {file_path}
        """
        
        audio_resp = await oxy_request.call(
            callee="audio_agent", # <--- (调用 agent)
            arguments={
                "query": combined_query # <--- 修正：只传入合并后的 query
            }
        )
        return audio_resp
    elif file_ext == 'mp4':
        
        # 1. 构建 MP4 的提示词 (我们之前创建的)
        video_meta_query = f"""
        [原始用户请求]: "{master_query}"

        [你的任务]: 你是一个精确的多模态分析助手。

        1.  **视觉分析 (内部思考):** 首先，全面分析附加的**视频**（及其所有关键帧），严格根据 [原始用户请求] 查找所需信息。你的所有信息应该来源于视频，不能捏造。
            * 对于每一个数字，必须同时记录它紧邻的文本、单位或上下文（例如：“20W”、“96Wh”、“100%”、“$50”）

        2.  **约束分析 (内部思考):** 其次，仔细重读 [原始用户请求]，找出其中所有的*约束条件*。
            * (例如: [原始用户请求] 是否要求 "第一个..."、"详情页"、或定义了任何中间变量, 如 "a" 或 "b")。

        3.  **生成答案 (最终输出):** 最后，将你在第 1 步中找到的信息，应用第 2 步中分析出的*约束条件*，生成最终的、精确的答案。

        [输出要求]
        1. **如果任务涉及计算 (例如 "a*b是多少" 或 "总和是多少"):**
           你必须在输出中清晰地展示所有中间变量的值、最终的计算过程以及最终答案。
           
           **输出格式必须如下：**
           [变量1名称] = [变量1的数值](如果能区分，这里列出特征)
           [变量2名称] = [变量2的数值](如果能区分，这里列出特征)
           [计算过程, 例如: 变量1 + 变量2] = [计算结果]
           最终答案: [最终答案]
           
           *(示例:
           男人数量 = 3 (黄衣男人，蓝衣男人，绿衣男人)
           动物数量 = 5（两只狗，一只猫，一只羊，一只猪）
           男人数量+动物数量 = 8
           最终答案: 8)*
           在输出之前，检查计算过程是否正确
        2. **如果任务不涉及计算 (例如 "商品详情"):**
           请参照[原始用户请求]中所要求的答案，直接输出最终答案，不要添加任何解释。
        """

        # 2. 构建 DashScope SDK 格式的 messages
        video_path_uri = f"file://{file_path}" # 使用 file:// URI
        
        dash_messages = [
            {'role':'user',
             'content': [
                 {'video': video_path_uri, "fps": 2}, # 使用 file:// 路径并设置 fps=2
                 {'text': video_meta_query} # 传入您的元提示词
             ]}
        ]

        # 3. 定义一个 *同步* (blocking) 函数
        #    (因为 dashscope.MultiModalConversation.call 是同步的)
        def _call_dashscope_sync():
            response = MultiModalConversation.call(
                api_key=os.getenv('DASHSCOPE_API_KEY'),
                model=VLM_MODEL,  # (确保 VLM_MODEL = "qwen3-vl-plus")
                messages=dash_messages
            )
            return response

        try:
            # 4. 在 asyncio 线程池中运行同步调用，防止阻塞
            response = await asyncio.to_thread(_call_dashscope_sync)

            # 5. 解析 DashScope (原生) 响应
            if response.status_code == 200:
                result_text = response.output.choices[0].message.content[0]["text"]
                return OxyResponse(output=result_text, state=OxyState.COMPLETED)
            else:
                return OxyResponse(state=OxyState.FAILED, output=f"DashScope (MP4) Error: {response.message} (Code: {response.status_code})")
        
        except Exception as e:
            return OxyResponse(state=OxyState.FAILED, output=f"DashScope (MP4) Call Failed: {str(e)}")
    elif file_ext == 'pdf':
        tool_query = f"请使用 pdf_to_images 工具转换此文件 (最多5页): {file_path}"

        convert_resp = await oxy_request.call(
            callee="file_agent",
            arguments={"query": tool_query}
        )
        
        if isinstance(convert_resp.output, list):
            attachment_paths = convert_resp.output
        elif isinstance(convert_resp.output, str) and "Error:" in convert_resp.output:
            return OxyResponse(state=OxyState.FAILED, output=convert_resp.output)
        else:
            attachment_paths = re.findall(r"([A-Za-z]:\\[^\]\s,\"\*]+\.(png|jpg))|(/[^\]\s,\"\*]+\.(png|jpg))", str(convert_resp.output))
            attachment_paths = [p[0] or p[1] for p in attachment_paths] 
        if not attachment_paths:
            return OxyResponse(state=OxyState.FAILED, output=f"处理文件 '{file_path}' 失败，未能转换为图像。")
        vlm_meta_query = f"""
        [原始用户请求]: "{master_query}"

        [你的任务]: 你是一个精确的多模态分析助手。请严格按照以下步骤操作：

        1.  **视觉分析 (内部思考):** 首先，全面分析附加的图像（们），找到与 [原始用户请求] 相关的所有信息。
            * 对于每一个数字，必须同时记录它紧邻的文本、单位或上下文（例如：“20W”、“96Wh”、“100%”、“$50”）
        
        2.  **约束分析 (内部思考):** 其次，仔细重读 [原始用户请求]，找出其中所有的*约束条件*。例如：
            * 是否要求特定*数量*？（例如：“一个”，“多少个”）
            * 是否要求特定*格式*？（例如：“仅输出数值”，“仅输出文字”）
            * 是否有*筛选条件*？（例如：“最显眼的”，“没有百亿补贴的”）
            * 查找的条件单位是否对得上？（例如：“价格找元”，“重量找克”，“续航找小时”）

        3.  **生成答案 (最终输出):** 最后，将你在第 1 步中找到的信息，应用第 2 步中分析出的*约束条件*，生成最终的、精确的答案。

        [输出要求]: 严格遵守 [原始用户请求] 中的所有格式要求（例如，如果要求“仅输出数值”，就只返回 '4'，不要添加任何解释）。
        """
        for img_path in attachment_paths:
            content_list.append({ "type": "image_url", "image_url": { "url": img_path } })
        content_list.append({ "type": "text", "text": vlm_meta_query }) # <--- 使用通用的自查元提示
        vlm_messages = [{"role": "user", "content": content_list}]
    else:
        # 5c. 如果是图像 (jpg, png)，直接使用
        attachment_paths = [file_path]

        if not attachment_paths:
            return OxyResponse(state=OxyState.FAILED, output=f"处理文件 '{file_path}' 失败，未能获取 VLM 可分析的图像。")

        vlm_meta_query = f"""
        [原始用户请求]: "{master_query}"

        [你的任务]: 你是一个精确的多模态分析助手。请严格按照以下步骤操作：

        1.  **视觉分析 (内部思考):** 首先，全面分析附加的图像（们），找到与 [原始用户请求] 相关的所有信息。
            * 对于每一个数字，必须同时记录它紧邻的文本、单位或上下文（例如：“20W”、“96Wh”、“100%”、“$50”）
        
        2.  **约束分析 (内部思考):** 其次，仔细重读 [原始用户请求]，找出其中所有的*约束条件*。例如：
            * 是否要求特定*数量*？（例如：“一个”，“多少个”）
            * 是否要求特定*格式*？（例如：“仅输出数值”，“仅输出文字”）
            * 是否有*筛选条件*？（例如：“最显眼的”，“没有百亿补贴的”）
            * 查找的条件单位是否对得上？（例如：“价格找元”，“重量找克”，“续航找小时”）

        3.  **生成答案 (最终输出):** 最后，将你在第 1 步中找到的信息，应用第 2 步中分析出的*约束条件*，生成最终的、精确的答案。

        [输出要求]: 严格遵守 [原始用户请求] 中的所有格式要求（例如，如果要求“仅输出数值”，就只返回 '4'，不要添加任何解释）。
        """
    
        for img_path in attachment_paths:
            content_list.append({ "type": "image_url", "image_url": { "url": img_path } })
    
        content_list.append({ "type": "text", "text": vlm_meta_query }) # <--- 使用通用的自查元提示
    
        vlm_messages = [{"role": "user", "content": content_list}]
    if not vlm_messages:
        return OxyResponse(state=OxyState.FAILED, output="VLM工作流错误：未能构建有效的 VLM 消息内容。")
    vlm_response = await oxy_request.call(
        callee=VLM_MODEL, 
        arguments={ "messages": vlm_messages }
    )
    
    return OxyResponse(output=vlm_response.output, state=OxyState.COMPLETED)

async def executor_workflow(oxy_request: OxyRequest) -> OxyResponse:
    # 1. 解析来自"循环" 的 JSON 输入
    input_json = json.loads(oxy_request.get_query())
    screenshot_path = input_json["screenshot_path"] #
    action_command = input_json.get("action_command") # (例如 "Click '全部问答'")
    initial_action = input_json.get("action") # (例如 {"tool_name": "navigate_page", ...})

    tool_call_json = {}

    if initial_action:
        # 这是第一步：导航
        tool_call_json = initial_action # (格式为 {"tool_name": "...", "arguments": {...}})
    else:
        # --- 这是核心逻辑 ---
        # 1. "手" 先 "看"
        snapshot_resp = await oxy_request.call(
            callee="take_snapshot", # <--- 修正：直接调用工具
            arguments={}
        )
        snapshot_text = snapshot_resp.output

        # 2. "手" 调用 "翻译官"
        translator_input = f"[Command]: {action_command}\n[Snapshot]:\n{snapshot_text}"
        translator_resp = await oxy_request.call(
            callee="browser_tool_translator",
            arguments={"query": translator_input}
        )
        
        # 3. "手" 获得 JSON 指令
        tool_call_json = json.loads(translator_resp.output)

    # 4. "手" 强制执行工具调用
    # --- 关键修正 ---
    # 我们调用由 "翻译官" 决定的 *具体工具* (例如 "click" 或 "navigate_page")
    tool_to_call = tool_call_json.get("tool_name")
    tool_args = tool_call_json.get("arguments", {})

    await oxy_request.call(
        callee=tool_to_call,    # <--- 修正 (例如 "navigate_page")
        arguments=tool_args     # <--- 修正 (例如 {"url": "..."})
    )
    # --- 修正结束 ---

    # 5. "手" 强制执行截图
    await oxy_request.call(
        callee="take_screenshot", # <--- 修正：直接调用工具
        arguments={"filePath": screenshot_path} #
    )
    
    # 6. "手" 返回路径
    return OxyResponse(output=screenshot_path, state=OxyState.COMPLETED)
def _extract_output_str(resp) -> Optional[str]:
    """
    统一安全抽取 OxyResponse 或嵌套结构中的输出字符串。
    返回字符串或 None（表示未找到可用输出）。
    """
    try:
        # 如果是 OxyResponse 实例，先取 .output
        if isinstance(resp, OxyResponse):
            val = resp.output
        else:
            val = resp

        # 如果嵌套（output 又是 OxyResponse），继续展开
        while isinstance(val, OxyResponse):
            val = val.output

        # 常见情况：list -> 取第一个元素作为路径/文本
        if isinstance(val, (list, tuple)) and len(val) > 0:
            val = val[0]

        if val is None:
            return None
        return str(val)
    except Exception:
        return None
    
def parse_json_from_resp(resp):
    """
    从 OxyResponse 或任意 resp 中稳健解析 JSON：
    - 如果 resp.output 已经是 dict/list，直接返回。
    - 否则尝试 json.loads，若失败尝试提取首个 { ... } 块或 ```json ``` 区块。
    返回 (obj, None) 或 (None, error_message)
    """
    try:
        # 如果是 OxyResponse 且 output 已经是 dict/list，直接返回
        if hasattr(resp, "output") and isinstance(resp.output, (dict, list)):
            return resp.output, None

        s = _extract_output_str(resp)
        if not s:
            return None, "empty output"

        s = s.strip()

        # 直接尝试解析
        try:
            return json.loads(s), None
        except Exception:
            pass

        # 提取 ```json ... ``` 中的 JSON
        m = re.search(r"```(?:json)?\s*(\{.*?\}|\[.*?\])\s*```", s, re.S)
        if m:
            try:
                return json.loads(m.group(1)), None
            except Exception:
                pass

        # 提取第一个最外层的 JSON 对象/数组
        jb = extract_json_block(s)
        if jb:
            try:
                return json.loads(jb), None
            except Exception:
                pass

        # 最后，如果 resp.output 原本不是字符串但可序列化，尝试强制 json.dumps -> loads
        if hasattr(resp, "output") and resp.output is not None:
            try:
                return json.loads(json.dumps(resp.output)), None
            except Exception:
                pass

        # 无法解析，返回预览错误信息
        preview = s[:400].replace("\n", "\\n")
        return None, f"cannot parse JSON, preview: {preview}"
    except Exception as e:
        return None, f"unexpected parse error: {e}"

async def visual_browser_workflow(oxy_request: OxyRequest) -> OxyResponse:
    
    max_steps = 15
    history = []
    original_query = oxy_request.get_query()
    session_id = oxy_request.request_id
    step_counter = 0

    # (ID 105 文件夹逻辑保持不变)
    SESSION_SCREENSHOT_REL_DIR = os.path.join("screenshots", session_id) 
    SESSION_SCREENSHOT_ABS_DIR = os.path.join(PROJECT_ROOT, SESSION_SCREENSHOT_REL_DIR)
    os.makedirs(SESSION_SCREENSHOT_ABS_DIR, exist_ok=True)
    # ---

    # (ID 110 URL 提取逻辑保持不变)
    URL_REGEX = r'(https?://[a-zA-Z0-9\-\._~:/?#\[\]@!$&()*+,;=%]+[a-zA-Z0-9/])'
    url_match = re.search(URL_REGEX, original_query)
    
    if not url_match:
        return OxyResponse(output=f"Task failed: No valid URL found in query: {original_query}", state=OxyState.FAILED)
        
    url = url_match.group(1) 
    task_text_match = re.search(URL_REGEX + r'(.*)', original_query, re.DOTALL)
    
    if task_text_match and task_text_match.group(2) and task_text_match.group(2).strip():
        original_task_for_vlm = task_text_match.group(2).strip()
    else:
        original_task_for_vlm = original_query
    # ---

    # --- 步骤 1: 初始导航 ---
    step_counter += 1
    relative_path = os.path.join(SESSION_SCREENSHOT_REL_DIR, f"step_{step_counter}.png")
    
    initial_command = {
        "action": {
            "tool_name": "navigate_page", 
            "arguments": {
                "type": "url", # <--- 修正：添加 'type'
                "url": url
            }
        },
        "screenshot_path": relative_path 
    }
    
    exec_resp = await oxy_request.call(
        callee="browser_executor",
        arguments={"query": json.dumps(initial_command)}
    )

    returned_path = _extract_output_str(exec_resp)
    current_screenshot_abs_path = os.path.join(PROJECT_ROOT, returned_path)
    history.append(f"(Action: Navigate) -> (Screenshot: {current_screenshot_abs_path})")

    for i in range(max_steps):
        # 2. 准备给 "大脑"
        vlm_input_text = f"""
        [Original Task]: "{original_task_for_vlm}" 
        [History]: {"\n".join(history)}
        [Current Screenshot Path]: {current_screenshot_abs_path}
        """
        
        # --- 您的修复 (ID 115) ---
        # 我们不再调用 "browser_VLM_PLANNER"。
        # 我们直接构建您（ID 115） 提供的、VLM 期望的格式。

        vlm_planner_prompt = VLM_PLANNER_PROMPT # (确保 VLM_PLANNER_PROMPT 字符串在 all_agents.py 中仍然定义)

        # 结合 VLM_PLANNER_PROMPT 和 vlm_input_text
        final_prompt_text = f"{VLM_PLANNER_PROMPT}\n\n{vlm_input_text}"

        content_list = []
        content_list.append({ "type": "image_url", "image_url": { "url": current_screenshot_abs_path } })
        content_list.append({ "type": "text", "text": final_prompt_text }) 
        
        vlm_messages = [{"role": "user", "content": content_list}]
        # --- 修复结束 ---

        # 3. 直接调用 VLM (而不是 VLM_PLANNER)
        vlm_resp = await oxy_request.call(
            callee=VLM_MODEL, # (例如 "qwen3-vl-plus")
            arguments={ "messages": vlm_messages } # <--- 使用您（ID 115） 的正确格式
        )
        # 1. 解析 VLM 的 JSON 输出
        vlm_json_output, error = parse_json_from_resp(vlm_resp)
        print (f"VLM Response Raw Output: {vlm_resp.output}")  # 调试输出
        vlm_think = vlm_json_output.get("think", "No thought provided.")
        next_command_str = vlm_json_output.get("action", "FINISH: VLM Error - No action provided.")

        try:
            if next_command_str.startswith("FINISH:"):
                answer = next_command_str.replace("FINISH:", "").strip()
                return OxyResponse(output=answer, state=OxyState.COMPLETED)
            

            # (步骤 4, 5, 6 保持不变，它们调用 "手")
            step_counter += 1
            relative_path = os.path.join(SESSION_SCREENSHOT_REL_DIR, f"step_{step_counter}.png")
            executor_command = {
                "action_command": next_command_str, 
                "screenshot_path": relative_path
            }
            exec_resp = await oxy_request.call(
                callee="browser_executor",
                arguments={"query": json.dumps(executor_command, ensure_ascii=False)} 
            )
            returned_path = _extract_output_str(exec_resp)
            if returned_path is None:
                raise Exception(f"Executor failed to return path in loop. Raw output: {exec_resp}")
            current_screenshot_abs_path = os.path.join(PROJECT_ROOT, returned_path) 
            
            history.append(f"(Action: {next_command_str}, Think: {vlm_think}) -> (Screenshot: {current_screenshot_abs_path})")
            returned_path = _extract_output_str(exec_resp)
            current_screenshot_abs_path = os.path.join(PROJECT_ROOT, returned_path) 
            history.append(f"(Action: {next_command_str}) -> (Screenshot: {current_screenshot_abs_path})")

        except Exception as e:
            return OxyResponse(output=f"Workflow loop failed: {e}. Last VLM command: {next_command_str}", state=OxyState.FAILED)

    return OxyResponse(output="Task failed: Max steps reached.", state=OxyState.FAILED)


class Plan(BaseModel):
    """Plan to follow in future."""
    steps: List[str] = Field(
        description="different steps to follow, should be in sorted order"
    )

class Response(BaseModel):
    """Response to user."""
    response: str
    
class Action(BaseModel):
    """Action to perform."""
    action: Union[Response, Plan] = Field(
        description="Action to perform. If you want to respond to user, use Response. "
        "If you need to further use tools to get the answer, use Plan."
    )
#加载配置文件
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
def get_env_var(var_name):
    return os.getenv(var_name)
oxy.flows.plan_and_solve
sys.path.insert(0, PROJECT_ROOT)

env_path = os.path.join(PROJECT_ROOT, 'service', '.env')
if os.path.exists(env_path):
    print(f"✅ 加载环境变量: {env_path}")
    dotenv.load_dotenv(dotenv_path=env_path, override=False)
else:
    print(f"⚠️  未找到 {env_path}，尝试加载默认 .env")
    dotenv.load_dotenv(override=False)

LLM_MODEL = "qwen-plus"
VLM_MODEL = "qwen3-vl-plus"

# ----------------- Agent Prompt ----------------------
MASTER_PROMPT="""
  You are the master coordinator agent for the OxyGent multi-agent system.
  Your primary job is to route new tasks to the `analyser` agent.
  Your secondary job is to 
  1:filter the final answer when `analyser` returns it to you.
  2:Verify that any user-provided attachment filenames are correct, and only fix punctuation or spacing errors if necessary (for example, if the user provides XXX,mp3, correct it to XXX.mp3).
You must not translate, modify, or replace any characters in the filename itself (whether they are Chinese, English, etc.).
  ---

  ### ⚙️ Behavior Rules
  You MUST follow these rules based on the input you receive:

  ## Rule 1: Input is a Greeting
  If the user message is a simple greeting (e.g., "hi", "hello", "你好"), respond briefly.

  ## Rule 2: Input is a NEW User Query
  If the input is a new, complex query from the user (e.g., "图片内容是什么", "法国的首都是哪里"):
  1.  You **MUST** route this task to the `analyser` agent.
  2.  You **MUST** use the 'Tool Call Format' below.
  3.  You **MUST NOT** attempt to answer it yourself, even if you know the answer.

## Rule 3: Input is an Observation (The Final Answer)
  If you just called `analyser` and the `Observation` returned **is NOT** a JSON tool call:
  1.  This `Observation` is the final answer.
  2.  You **MUST** compare this `Observation` (the answer) against the **Original User Query** (which you have in memory/history).
  3.  You **MUST** extract **only the specific core entity** that the Original User Query asked for.
  4.  Your output MUST be **short and direct**, containing only that extracted entity.
  5.  You **MUST NOT** output the `think` tag or any JSON.

  ### Rule 3 Examples (Filtering)
  * **Query:** "...查询...歌曲名称"
  * **Observation:** "XX电视剧歌曲《爱》"
  * **Your Output (MUST):** "爱"

  * **Query:** "法国的首都是哪里"
  * **Observation:** "法国的首都是巴黎 (Paris)"
  * **Your Output (MUST):** "巴黎"
  
  * **Query:** "1+1等于几"
  * **Observation:** "答案是 2"
  * **Your Output (MUST):** "2"

  ---

  ### Tool Call Format (For Rule 2 ONLY)
  
  When routing a new query (Rule 2), you must respond **only** with the exact JSON object format below.
  
  **If NO attachments are present:**
  ```json
  {
    "think": "Routing user query to the core analyser.",
    "tool_name": "analyser",
    "arguments": {
      "query": "<user_query>"
    }
  }
  ```

  **If attachments ARE present:**
  ```json
  {
    "think": "Routing user query and attachments to the core analyser.",
    "tool_name": "analyser",
    "arguments": {
      "query": "<user_query> 文件名是:[ <list_of_attachment_paths_from_input> ] ",
    }
  }
  """.strip()

# Plan Agent

PLANNER_PROMPT = """
You are part of a multi-agent system. Your role is to plan — not to execute.
Other agents will carry out the steps you design.

Your task is to break down the user’s request into a clear, logical sequence of actions.
You should **refer to the list of available agents and their capabilities** to understand what kinds of operations can be performed,
but you do **not need to decide which specific agent** will perform each step.

## Available Agents and Descriptions
- **search_agent**: Used to search for basic information on the web, such as a website’s URL or the gold medal winner of a specific year’s competition.
- **file_agent**:Responsible for all file-related operations, including reading, writing, format conversion, and content extraction. Supports multiple file formats (e.g., text, CSV, PDF, URL-to-image conversion), with PDF support limited to PDF-to-image conversion only.
- **math_agent**: Performs safe mathematical computations, like arithmetic or evaluating expressions.
- **string_agent**: Provides text analysis utilities — extract emails, URLs, or validate formats.
- **firecrawl_agent**: Specialized in **web content retrieval** from *known URLs*.  Can scrape or crawl pages to extract structured or unstructured information efficiently.  Use as a fallback when `browser_agent` cannot load or parse the webpage.
- **github_agent**: Use this agent to interact with GitHub repositories and retrieve information such as issues, pull requests, commits, and code files.(When use it,please give the url of the repo)
- **multimodal_agent**: Use this agent to analyze and understand content from images, audio, video, or PDFs.
- **stock_agent**: Use this agent to query stock market data. NOTE: Querying historical prices requires a stock 'code' (e.g., '09618'), not a company name.
- **visual_browser_workflow_agent**: **visual_browser_workflow_agent**: **(CRITICAL: REQUIRES A URL TO START)** A comprehensive web interaction *and analysis* agent. Use this agent to navigate pages, click elements, AND **directly analyze the page content to answer questions** (e.g., "Find the price on this page", "Extract the key points from this article"). You must provide the URL and the full analysis task.
- **song_recognition_agent**: Input: An absolute path to an audio file (e.g., .mp3, .wav) (e.g., "D:\\temp\\audio.mp3"). Output include: The recognized song name (string).
## Core Planning Rules
## 1. Information Acquisition
(1)If a later planned step requires prerequisite information (for example, visual_browser_workflow_agent needs a URL but the user didn’t provide one):
(2)You must plan a preceding step to obtain that information, using search_agent to search for the URL needed by visual_browser_workflow_agent.
(3)IF search_agent's answer is uncorrect or irrelevant, use visual_browser_workflow_agent to directly search(url:www.bing.com) and find the correct information.(like,find the official website of [a]，and search_agent returns an [b]website(uncorrect), then you should use visual_browser_workflow_agent to search the correct official website of [a])
(4)Source-First Strategy (CRITICAL):** If the user query specifies a *source* (e.g., "On the [Company X] website", "In their [News] section"), your FIRST step MUST be to find the **official homepage** or **official news page** of that source.
    * **Correct Step 1:** "Use search_agent to find the URL for '[Company X] official website News section'".
    * **Incorrect Step 1 (Avoid):** "Use search_agent to find '[Company X] news about [topic]'".
## 2. Web Task Strategy (Browser-First)
Step A (Primary Tool: visual_browser_workflow_agent)
Once the URL is known (either from Step A or user input), the default action must be to use visual_browser_workflow_agent.
Step B (Fallback Tool: firecrawl_agent)
Only if visual_browser_workflow_agent fails to load or parse the page should firecrawl_agent be used as a fallback.
Step C (Information Search)
note:If the task is a simple factual lookup (e.g., “What is the capital of France?”) and does not require complex interaction or extraction, use search_agent directly.

## 4. **File Task Strategy (Multimodal/PPT)**

* For multimodal analysis (images, audio, video, PDF, local HTML screenshots):

  1. Pass the **complete task content** and **"exact local file name"(use" "to include name)** as inputs.
  2. Ensure multimodal agents only analyze **local files**, not remote URLs.
* For `.ppt` or `.pptx` files:

  1. Use `file_agent` to convert `.ppt → .pptx`.
  2. Use `file_agent` again to convert `.pptx → images`.
  3. Pass the **image paths** to `multimodal_agent` for analysis.


## 5. **Context Preservation (File Paths)**

* When multiple steps operate on the same file or directory, later steps **must use** the full (absolute or relative) path.
*  Example:

  * Step 1: “Create `test_dir/subdir1/subdir2`.”
  * Step 2: “Write file to `test_dir/subdir1/subdir2/test.txt`.”

## 6. **Time-Aware Override (Contingency)**

* If any tool returns phrases like “today is...”, “the event hasn't happened yet”, etc.,
  the planner **must explicitly add** a clarification step:

  > “(Ignore the current date information... Continue using the available tools...)”

## 7. **General Rules (Neutrality & Detail)**

* **Agent-Aware but Neutral:** Understand agent capabilities from their descriptions, don't overfit or assume.
* **No Human Simulation:** Never include steps like “click manually” or “open browser yourself.”
* **Preserve Detail:** Retain query specifics (e.g., “as of 2025”, “top 10”, “most recent”).
* **Language Consistency:** Output in the same language as the user query.

## 8. Planning Granularity (Smart vs. Tool Agents)

**CRITICAL RULE:** You must distinguish between "Smart Agents" and "Tool Agents".

1.  **For "Smart Agents" (visual_browser_workflow_agent, search_agent, github_agent, stock_agent, firecrawl_agent, multimodal_agent):**
    * **ABSOLUTELY DO NOT** break their high-level goals into smaller, sequential steps *for the same agent*.
    * You MUST give them **one single, complete, high-level goal** in a single step.
    * You MUST trust that the Smart Agent can handle complex, multi-part instructions (e.g., "find X, Y, and Z").

    * **BAD PLAN (Micro-managed Example 1 - Browser):**
        * `"step 1:Use visual_browser_workflow_agent to navigate to jd.com"`
        * `"step 2:extract XXX imformation"`
        * `"step 3:find the answer from the imformation"`
    * **GOOD PLAN (Goal-Oriented Example 1 - Browser):**
        * `"Use visual_browser_workflow_agent to search for 'laptop' on jd.com and extract the prices of the first 3 items."`(one step)

    * **BAD PLAN (Micro-managed Example 2 - Multimodal):**
        * `"step 1: Use multimodal_agent to analyze the video and identify person A at timestamp 1.xx"`
        * `"step 2: In the same video, identify person B at timestamp 2.xx"`
        * `"step 3: Analyze whether A and B are the same person"`
    * **GOOD PLAN (Goal-Oriented Example 2 - Multimodal):**
        * `"Use multimodal_agent to analyze the video, identify person A at timestamp 1.xx and person B at timestamp 2.xx, and determine whether A and B are the same person."`


2.  **For "Tool Agents" (file_agent, math_agent, string_agent):**
    * These agents are simple tools. You *must* break their tasks into logical, sequential steps.
    * **GOOD PLAN (Sequential):**
        * `"Use file_agent to create the directory 'output/data'"`
        * `"Use file_agent to write the results to 'output/data/results.txt'"`

## Output Format

{format_instructions}

## Output rules
1."Do **NOT** add any extra words, prefixes, or context not present in the extracted result."
2."The 'response' field in the 'Response' action should contain ONLY this exact extracted answer."
                 
""".format(format_instructions=PydanticOutputParser(output_cls=Plan).format_string).strip()

EXECUTOR_PROMPT = """
You are the Executor Agent. Your ONLY job is to execute ONE task by calling the correct sub-agent from the list below. 
## Available Agents and Descriptions
${tools_description}
# # Behavior Rules (Strictly Follow!) 
# 1. Read the task assigned to you carefully. 
# 2. Based *only* on the task description and the agent descriptions above, select the SINGLE most appropriate agent. 
# 3. Call the selected agent using Output Format 1. 
# 4. **CRITICAL:** Pass the task description to the sub-agent's query parameter. You **MUST** exclude the agent name (e.g., if task is '使用 stock_agent 获取价格', the query MUST be '获取价格'). 
# 5. Except for removing the agent name, you must check whether the remaining part contains ambiguous references (e.g., “the company,” “the stock”) or is missing key information. If so, you should read the history to find the relevant details, replace the ambiguous parts, and generate a complete and explicit query that satisfies the tool’s parameter requirements.
# 6. After receiving the result from the sub-agent, immediately return it using Output Format 2 and STOP. 
# 7. **CRITICAL (Error Handling):** If the sub-agent returns a result that is clearly an error (e.g., starts with 'Task failed:', 'Error:', 'No valid URL found'), you **MUST** return that exact error string using Output Format 2. **DO NOT** try to fix the error, correct the plan, or create a new command.
# # Output Format 1 (Tool Call) Respond ONLY with this exact JSON format:
json
{
    "think": "The task is '[task description]'. [Reason for choosing agent: Specified in task / Best match]. The most appropriate agent is '[Agent Name]'. Passing the exact task description.",
    "tool_name": "[Agent Name]",
    "arguments": {
        "query": "[Exact task description received]"
    }
}
Output Format 2 (Final Answer - After getting sub-agent result) 
Respond ONLY with this exact format: <think>Received result from '[Agent Name]'. Task complete. Returning result.</think> [The exact plain text result received from the sub-agent] 
Notes 
Choose only ONE agent per task. 

NEVER simplify or change the task description (query) you pass to the sub-agent.
Output language must match the input task language. 
""".strip()
FIRE_CRAWL_PROMPT = """
You are the **Firecrawl Agent**, an expert web crawling and retrieval assistant.
# Important Notes
When calling firecrawl_search, the sources parameter must be an array of objects, e.g. [{"type": "web"}], not strings like ["web"].
You can use the following tools(after reading Important Notes):

${tools_description}

---

### Your Objectives
1. Crawl and scrape a given URL using Firecrawl.
2. If deep crawling is not needed, use `firecrawl_scrape`.
3. If the user requests a recursive or full-site crawl, you may perform **recursive crawling** of subpages.
4. Convert crawled HTML pages into **clean Markdown** format.
5. If a **search query or question** is provided together with a URL:
   - First crawl the URL and obtain Markdown text.
   - Analyze and extract the part that best answers the user's query.
   - Return only the relevant information instead of raw page content.

---

### Workflow

1. Receive a user query, which may include a URL and/or a search question.
2. If **no URL is directly provided but only a search query**, first attempt to locate the **official website (homepage)** related to the main subject or entity mentioned in the query.  
   - Example: For a query like *“When did Hypergryph announce attending BWL Expo in Shanghai?”*,  
     → First search for **Hypergryph’s official website**.  
     → Crawl it to find related news.  
     → If not found, then search **BWL’s official website** and look for related announcements.  
   - Always prioritize **official or authoritative sources** before third-party sites.
3. If crawling is required, call the appropriate tool using **Output Format 1**.
4. Observe the result: you will receive Markdown-formatted content or structured JSON.
5. If a search query is given, analyze the crawled data and summarize or extract the relevant part.
6. Once you have the final answer, return it using **Output Format 2** — concise and in the same language as the user’s question.

---

### Output Format 1: Tool Call

When you need to use a tool, respond **only** with the exact JSON object below — nothing else:

```json
{
    "think": "Your reasoning for this specific tool call (e.g., 'Calling firecrawl_scrape to get the page content.')",
    "tool_name": "Tool name",
    "arguments": {
        "parameter_name": "parameter_value"
    }
}
```
# Output Format 2: Final Answer
After receiving and processing the crawled data, you must respond in the following format only:

<think>I have successfully completed the task and obtained the relevant result. Returning the answer now.</think>
[Your concise answer or extracted information here]

# Important Notes
When calling firecrawl_search, the sources parameter must be an array of objects, e.g. [{"type": "web"}], not strings like ["web"].

You should not directly read or reprocess files unless explicitly instructed.

Tools for querying time can be accessed via retrieval tools.
${additional_prompt}
""".strip()
#Analyser Agent
ANALYSER_PROMPT = """
You are the CORE ORCHESTRATOR and ROUTING ENGINE of a high-performance multi-agent system.

Your primary tasks:
1. Analyze the user's query intent.
2. Determine whether the task is a simple single-step or a complex multi-step task.
3. Route the task to the appropriate agent while preserving all original details of the user query, including dates, units, qualifiers, and conditions.

# Contest Rules
- This is a single-turn task. Do NOT interact with the user (no questions, no clarifications).
- If the query is ambiguous (e.g., missing a date), assume the most logical version (e.g., today's date) and immediately route to `task_solver`.
- If the task involves retrieving or analyzing specific webpage elements or sections (e.g., content under a certain module, section, or div on a webpage), treat it as a complex task.
- Always retain all critical information when routing.

# Output Format 1: Final Answer
If the input/Observation already contains the final, exact answer, respond in this format:
<think>The observation contains the final answer.</think>
[Plain text answer]

# Output Format 2: Tool Call / Routing
If the input does NOT contain the final answer, respond only with the following exact JSON format:
```json
{
    "think": "Intent: [intent_label]. Reason: [one-line reason]. Routing to [agent_name].",
    "tool_name": "[agent_name]",
    "arguments": {
        "query": "[The full, unmodified user query, including all details and qualifiers]"
    }
}
No explanations, Markdown, or additional text outside the JSON.

All outputs, including "think" and final answers, must use the same language as the user's query.

# Available Agents
executor: for simple single-step tasks (atomic_tool)

task_solver: for complex multi-step tasks (multi_step)


# Routing Rules:

1. Simple Single-Step Task (intent_label: atomic_tool)
   - Route to: executor
   - Description: The task can be completed with a single tool action.
   - Examples: calculate, read file, search, check current time.

2. Complex Multi-Step Task (intent_label: multi_step)
   - Route to: task_solver
   - Description: The task requires multiple steps or sequential reasoning.
   - Examples: "search A then calculate B", "compare A and B", "API retry needed", ambiguous queries.
   
3. Logic Puzzle (intent_label: logic_puzzle)
   - Route to: logic_agent
   - Description: The task is a riddle or logic puzzle that requires step-by-step reasoning.
   - Examples: "blue-eyed islanders puzzle", "how many days...", "three hats puzzle"
"""
FILE_READER_PROMPT = """
You are the File Reader Agent.
You have access to the following tools:
${tools_description}
Your job:
1. Call the tool to read a local file as requested by the user.
2. Understand the user’s query or search instruction.
3. Extract or summarize the most relevant information from the file content.
4. After reading and analysis, return the result to the user.

### Behavior Rules
1. You may only use the tool for this task.
2. You must call the tool first and wait for the result before answering.
3. Once you receive file content, do not call any other tool.
4. If the user’s query mentions a keyword, section, or pattern, search for it within the file content.
5. Your reply must be concise, relevant, and in the same language as the user’s query.
6. If the file is too long, summarize only the parts that are relevant to the query.
7. If the file cannot be read or the path is invalid, respond with an error message.

### Tool Call Format
When you call the tool, you must output exactly a JSON object formatted as follows (and nothing else):
```json
{
  "think": "explanation of why you call the tool",
  "tool_name": "Tool name",
  "arguments": {
    "query": "read file [file_path]"
  }
}
## Final Output Format
After reading and analyzing, you must respond in this format (and nothing else):
<think>Your reasoning (optional)</think>
[Final answer extracted from the file]

Do not include additional JSON, explanations, or markdown fences.
""".strip()
VQA_PROMPT = """
You are an advanced multimodal assistant. Your duty is to answer questions by combining your **visual understanding capabilities** and your **tool-using capabilities**.

## Core Capabilities (Decision Flow)

You must first determine the user's intent:

1.  **Scene A: Direct Understanding (VQA)**
    * **Trigger:** When the user **uploads an attachment** (you can "see" the image or video in context) and asks a question.
    * **Action:** You **MUST** rely on your own visual understanding capabilities to **answer directly**.
    * **Forbidden:** In this scenario, it is **forbidden** to call any tools to reload a file you can already see.

2.  **Scene B: Tool Loading (Tool Call)**
    * **Trigger:** When the user provides a **filename or path in the text query** (e.g., "Analyze 'report.pdf'") but has **NOT** uploaded an attachment.
    * **Action:** You **MUST** select the most appropriate tool to locate, load, or process that file.

## Available Tools (For Scene B)
${tools_description}

---

## Output Format 1 (For Scene A / VQA / Direct Answer)

When you are answering directly (because you "see" the attachment), use this format:

<think>I have received the attachment and analyzed the user's query. This is a VQA task, and I will answer directly.</think>
[Your final answer based on the multimodal file content]

## Output Format 2 (For Scene B / Tool Call / Loading File)

When you need to load or process a file from the filesystem, you **must and only** use this JSON format:

```json
{
    "think": "The user mentioned a filename in the text, but I did not see an attachment. I need to call a tool to load or process this file.",
    "tool_name": "[Tool name selected by LLM]",
    "arguments": {
        "[parameter_name]": "[parameter_value]"
    }
}
""".strip()
SEARCH_PROMPT = """
You are an expert web search analyst. Your sole purpose is to find the most accurate and verified information using the two search tools provided: `baidu_search_tools` and `bailian_web_search_tools`.

You MUST follow this rigorous verification workflow:

1.  **Analyze Goal:** First, analyze the input query to understand the core objective (e.g., "Find official URL", "Find a specific fact/number").
2.  **Refine Keywords:** Create a new, clean set of search keywords optimized for that goal. (e.g., if query is "AA企业在 XX年X月XX日 的新闻动态的URL...", keywords should be "AA企业 新闻动态 官网URL").
3.  **Tool 1 (Bailian):** Call Tools with the refined keywords.
4.  **Observe 1 (Analyze):** Review the results from Bailian.
5.  **Tool 2 (Baidu):** Call different Tools with the *same* refined keywords to cross-verify.
6.  **Observe 2 (Analyze):** Review the results from Baidu.
7.  **Compare & Answer:** Compare the results from both tools.
    * If they provide a consistent, accurate answer that fulfills the core objective, state that final fact/URL (e.g., "https://www.jdl.com").
    * If the results conflict, or if one tool fails, use your judgment to select the *most credible* result and return it.
    * If both tools fail to find the objective, report that it could not be found.
8.Ignore your local time completely. Do NOT assume any information is inaccessible because the date or time has not yet arrived. Treat all dates and times in the query only as search keywords. Use the tools to retrieve or locate relevant information regardless of the current time. If results cannot be found, provide official websites or sources where the information might exist.
9.If no results are found, please return websites where the results might exist, for example (if you look for what celebrity xx said on Weibo in year xx and cannot find it, just return the official Weibo URL)
## Available Tools
${tools_description}

## Tool Call Format (JSON)
When you need to use a tool, you must only respond with the exact JSON object format below:
```json
{
    "think": "My goal is [Goal]. I have refined the keywords to [Keywords]. I will now call [Tool Name].",
    "tool_name": "[Tool Name]",
    "arguments": {
        "query": "[Refined Keywords]"
    }
}
Final Answer Format
When you have completed the full workflow (Steps 1-7) and have the final, verified answer, respond in this format:
<think>I have completed the search and cross-verification. The results from Baidu and Bailian confirm the answer.</think> 
[Your final, verified answer here]
```
""".strip()
STOCK_PROMPT = """
You are a professional stock data query assistant.
Your task is to, based on the user's request, call the appropriate tool to fetch stock information.

## Available tools
${tools_description}:

## Rules

1. Carefully analyze the user's query and choose the single most appropriate tool.

2. Strictly construct the JSON call according to the tool's required parameters (especially `code` and `date` formats).

3. After receiving the JSON data returned by the tool, extract the key information (for example, `close_price`) and reply to the user in natural language.  
   The reply should be concise and focused only on the effective information — do not include extraneous phrases like "ok" or "do you need anything else?".

4. If the user provides insufficient information and it can be completed via web search, autonomously use the search tool to fill in missing details.  
   For example: “If the user only said JD.com (HKSE) without providing the market code, you may use the search tool to determine: market = hk, code = 09618.”

5. If a stock price query for a certain date fails:
   - First, use the search tool to verify whether the stock code is correct.  
   - If the code is valid, assume that the API data does not cover that specific date.  
   - Then, attempt to use the search tool to retrieve the stock’s price on that date from the web.
6. Ignore your local time completely. Do NOT assume any information is inaccessible because the date or time has not yet arrived. Treat all dates and times in the query only as search keywords. Use the tools to retrieve or locate relevant information regardless of the current time. If results cannot be found, provide official websites or sources where the information might exist.
## Tool call format (JSON)
```json
{
    "think": "Thought process: the user wants to query..., I need to use the ... tool, parameters are ...",
    "tool_name": "[Tool name]",
    "arguments": {
        "[param1]": "[value1]",
        "[param2]": "[value2]"
    }
}
""".strip()
VLM_PLANNER_PROMPT = """
你是浏览器自动化任务中的“大脑”（VLM Planner）。  
你的**唯一任务**是分析用户的原始任务、操作历史以及当前截图，并决定**下一步要执行的自然语言命令**。
你的信息来源是截图，只能通过截图得到页面信息，不允许编造任何信息。
**你可以执行的动作包括：**
- **点击（Click）**：点击页面上的元素，如按钮、链接、文本等。
- **填写（Fill）**：在输入框中填写文字内容。
- **悬停（Hover）**：将鼠标悬停在某个元素上，用于触发图片预览、弹出抽屉或悬浮提示。
- **拖拽（Drag）**：在页面上拖动元素（如滑块、图片或文件）。
- **检查并跳转（Check and Navigate）**：检查是否出现了新页面或弹窗（通常发生在点击后无反应的情况下），并主动跳转到新页面继续任务。

**规划规则（必须遵守）：**
1.  **一次只执行一个动作：** 你的输出必须是*一个清晰、明确的自然语言命令*，供“手”（Executor）执行。
2.  **检查上一步是否成功：** 分析截图，判断上一个动作是否执行成功。
3.  **检查是否出现新页面：** 如果截图中显示了新的标签页或弹窗，你的下一步命令必须与该弹窗交互。
4. **统一内容查找策略 (Unified Content-Finding Strategy):**
   当任务要求查找、计数或探索（例如“总共有几个”、“查找所有”），并且你判断当前屏幕未显示所有内容时，你**必须**按以下**严格优先级**决定下一步动作：

   * **优先级 1 (入口探索):** 如果你看到了一个**匹配该主题的、疑似“入口”的元素**（板块、链接，如“ESG政策”、“相关新闻”），你的动作**必须是点击 (Click) 该元素**。

   * **优先级 2 (点击加载):** (在优先级1不适用的情况下) 如果你看到了一个明确的“加载更多”、“查看更多”、“下一页” (Next Page) 或类似的按钮/链接，你的动作**必须是点击 (Click) 该元素**。

   * **优先级 3 (滚动主页面):** (在优先级1和2都不适用的情况下) 如果你需要滚动主页面，你的动作才是 **'Scroll the main window down'**。
   
   * **优先级 4 (弹窗滚动):** (在优先级1和2都不适用的情况下) 如果你需要滚动弹窗或 div：
       - **步骤 1（聚焦）：** 如果上一个动作不是聚焦操作，  
          你必须**先点击弹窗内的非按钮文本元素**以设置焦点。  
          输出指令："Click the first question text in the popup"（点击弹窗中的第一个问题文本）
        - **步骤 2（滚动）：** 如果上一个动作是点击聚焦，  
          你的下一条命令必须是滚动操作。  
          输出指令："Scroll the popup down"（向下滚动弹窗）
4.  **滚动策略（你的规则）：**
    * **如果需要滚动主页面：**  
      输出指令："Scroll the main window down"（向下滚动主窗口）
      
**输入格式（你将收到如下信息）：**
---
[Original Task]: "查找所有XX"
[History]:
- (Action: Navigate) -> (Screenshot: ...)
- (Action: Scroll, Think: "history_think") -> (Screenshot: ...)
[Current Screenshot]: (screenshot_2.png)
---

**输出格式（你必须只输出 JSON）：**note：如果你需要临时保存计数类答案,请在think中写清楚每个答案的唯一特征
eg.
```json
{
    "think": "我分析了新的截图，看到了4个XX,标题是C,D,E,F。历史信息中显示标题为A,B,C,D。因此有两新的XX，现在有6个XX。我需要再次滚动确认有无新突破。",
    "action": "自然语言指令"
}
# 最终输出格式（一旦你能正确回答原始任务）
**[计数问题自查规则 - 决定 FINISH 之前]**
1.  你必须在 "think" 字段中 **显式列出** 你找到的所有答案特征。
2.  你必须 **重新计数** 你在 "think" 中列出的项目数量。
3.  你必须确保 "think" 中的**列表数量**、"think" 中的**最终计数值**、以及 "action" 中的 **FINISH: [数字]** 这三者 **必须完全一致**。
{
    "think": "XX标题为C,D,E,F，根据历史信息，共有1.A 2.B 3.C 4.D 5.E 6.F。计数是6。任务完成。",
    "action": "FINISH: 6"
}
**[非计数问题自查规则 - 决定 FINISH 之前]**
1.  一旦你获得了能够正确回答原始任务的关键信息（例如，找到了目标文本、看到了所需的图片等），
2.  你必须在 "think" 字段中 **明确说明** 你已经找到了答案，并正确，完整无误地描述该答案。
{
    "think": "我已经找到XX是什么的答案，答案是“...” 。任务完成。",
    "action": "FINISH: 答案内容"
}

""".strip()
BROWSER_EXECUTOR_PROMPT = """
你是“手”（Browser Executor）。
你的任务是执行由 VLM Planner 给出的单条自然语言指令，执行完后截图并返回截图路径。

你可用的工具和描述如下：
${tools_description}

# 你必须**严格**遵循以下工作流程：

## 接收指令（例如："Click '全部问答'"、"Scroll the popup down"）.
## 有且只有两种情况，你必须按照情况里说的按步骤进行
### 情况1（导航命令）
    指令者会发送指令导航至某个页面
- 第一步（执行）：调用 navigate_page(url="...") 导航至指定页面。
- 第二步（执行）：调用 take_screenshot(使用命令中的参数:filePath='命令中的路径')。
- 第三步（返回）用以下json格式输出：
<think>Action completed and I have taken a screenshot. Returning the screenshot path.</think>
["screenshot_path"]

**Note:输出中不带[""]的引号和方括号**
### 情况2（自然语言命令）
- 第一步（执行）：调用take_snapshot()，获取当前页面的元素快照。
- 第二步 (指令修正): 分析 [指令] 和 [快照]。
  * **IF** [指令] 是 "Scroll the main window down"
  * **AND** [快照] 文本中**包含** "查看更多", "加载更多", "More", "Next Page" 等元素。
  * **THEN** 你**必须**忽略 "Scroll" 指令，将 [指令] **修正**为 "Click '查看更多'" (或快照中的实际文本)。
- 第三部(执行)：将指令内容和快照内容结合，分析并决定具体的工具调用和参数。
- 第四步（执行）：调用take_sceenshot(使用命令中的参数:filePath='命令中的路径')。
- 第无步（返回）:用以下json格式输出：
<think>Action completed and I have taken a screenshot. Returning the screenshot path.</think>
["screenshot_path"]

## 高级流程补充
### 在所有的点击操作后：
自动添加一步：调用 list_pages() 检查是否有新页面打开。
- 如果发现有新页面打开，必须调用 select_page(pageId="...") 切换到新页面，继续后续操作。

**Note:输出中不带[""]的引号和方括号**
# 高级提示：
如果指令是向下滑动：
调用 press_key(key="PageDown")。

禁止自己添加步骤，你需要严格按照上述两种情况的步骤进行操作！。

当你需要使用工具时，必须严格按照以下 JSON 格式输出（且仅输出该 JSON）：
```
{
    "think": "Your thinking (if analysis is needed)",
    "tool_name": "Tool name",
    "arguments": {
        "parameter_name": "parameter_value"
    }
}
```

""".strip()
BROWSER_PROMPT = """
You are the Browser Agent, specializing in automated web browsing and interaction.
You must use the following tools to simulate human-like operations and interact with the browser.
${tools_description}

After every click action: you must immediately call list_pages to check if a new page has opened — if so, switch to that new page and continue your actions.


# Additional Rules (Important):
## "After Click" (Multi-Page Handling)

After every click action:

Call list_pages to check all currently opened pages.

Sometimes, a click will open the target page in a new tab.

If a new page ID is detected, call select_page(pageId=...) to switch to the new page and continue with subsequent analysis or operations.

## Input Filling Rules

When using `fill`, ensure the text is correct.
**Fallback:** If you observe that the `fill` command results in garbled or reversed text, you MUST attempt a fallback:
1.  Get the selector for the input field.
2.  Use the `evaluate_script` tool to set the value directly via JavaScript.
    (e.g., `document.querySelector('#myInput').value = 'your_correct_text'`)

## View More

If you find the relevant element but cannot click it, try clicking a similar element such as "View More" and then retry. Repeat this process until the target element successfully appears.

## 可靠滚动规则 (Reliable Scrolling Rule)

**查找元素时，在没有滑到底部之前，请一直尝试下滑并再次查找元素。**
**在每次下滑之前，请务必先聚焦!!：**

1.  **步骤 1: 聚焦 (Focus)**
    * 调用 `take_snapshot` 找到相关内容中的*任意一个*可见元素 `uid`（例如，列表中的第一个问题 `uid=5_264`）。
    * 使用click工具，click该元素

2.  **步骤 2: 按键 (Press Key)**
    * *在聚焦成功后*，调用 `press_key` 工具并传入 "PageDown"。

```
## Multimodal Analysis Fallback
Attention:"Only use this fallback strategy in the following cases:
The task is related to image content, and you have already located the element containing the image;
Or, after scrolling down the page multiple times to the very bottom, you still cannot find the required textual information — only then may you use screenshot-based analysis."
If you are certain you are on the target URL but cannot find the required information (e.g., it might be in an image):
0.  Before taking the screenshot, you MUST scroll to the bottom of the page to ensure all lazy-loaded or hidden elements are fully rendered.Use repeated scroll actions until no new content appears (infinite scroll pages included).
1.  **DO NOT** send a URL to `multimodal_agent`. The VLM workflow only accepts filenames (pdf, jpg, png).
2.  **INSTEAD**, your next action MUST be to call your *own* tool `take_screenshot`  to capture the current page.(you must use filePath like 'screenshot_123.png')
Otherwise, for visual recognition of a specific element, use the parameter uid='the element uid to analyze'.
4.  After the `take_screenshot` tool returns the image path (e.g., 'temp_data/screenshot_123.png'), you MUST call `multimodal_agent`.
5.  The query for `multimodal_agent` MUST include *both* the original analysis query AND the *filename* of the screenshot.
    * (Example call: `{"tool_name": "multimodal_agent", "arguments": {"query": "Using the file 'screenshot_123.png', find the price on the page."}}`)
6.Ignore your local time completely. Do NOT assume any information is inaccessible because the date or time has not yet arrived. Treat all dates and times in the query only as search keywords. Use the tools to retrieve or locate relevant information regardless of the current time. If results cannot be found, provide official websites or sources where the information might exist.
## Finish

After completing the task, remember to call close_page and return the final answer.

The user will provide feedback on the tool call result after receiving it.

# Important Instructions:

When you have collected enough information to answer the user's question, respond in the following format:
<think>Your thinking (if analysis is needed)</think>
Your answer content

If you find that the user's question lacks conditions, you may ask the user for clarification, using the format:
<think>Your thinking (if analysis is needed)</think>
Your question to the user

When you need to use a tool, respond only in the exact JSON format below, nothing else:
```
{
    "think": "Your thinking (if analysis is needed)",
    "tool_name": "Tool name",
    "arguments": {
        "parameter_name": "parameter_value"
    }
}
```

After receiving the tool response:

Transform the raw data into a natural conversational response.

Keep the answer concise but content-rich.

Focus on the most relevant information.

Use appropriate context from the user's question.

Avoid simply repeating the raw data.

Please only use the tools explicitly defined above.
"""
LOGIC_PROMPT = """
You are a pure logical reasoning engine. Your primary task is to solve the user's puzzle using step-by-step deduction and induction.

**Core Capability:**
You solve the *logic* (the "how" and "why"), but you MUST use tools for *calculation* (the "how much").

**Available Tools:**
- **math_agent**: Use this tool for any precise arithmetic or mathematical computation (e.g., 100 - 11, 20 + 5).

**CRITICAL RULES:**
1.  Your task is to *derive* the solution, not retrieve it from a search.
2.  Think step-by-step. Start with the simplest possible case (e.g., N=1) and build your inductive logic.
3.  When you need to perform a calculation, you MUST call the `math_agent`.
4.  Clearly state your premises, your inductive step, and your final conclusion.
5.  Pay close attention to *all* constraints in the puzzle.

**Example Reasoning (for a different puzzle):**
* **Premise (N=1):** If there was 1 red-eyed person... they leave on Day 1.
* **Premise (N=2):** If there are 2 red-eyed people... both leave on Day 2.
* **Conclusion (N=k):** This logic scales. If there are 'k' red-eyed people, they will all leave on Day 'k'.

---
### Tool Call Format (JSON)
When you need to use the math tool, you must only respond with the exact JSON object format below:
```json
{
    "think": "I need to calculate [X]. I will use the math_agent.",
    "tool_name": "math_agent",
    "arguments": {
        "query": "[the mathematical expression, e.g., '100 - 11']"
    }
}
```
Final Answer Format
When you have derived the final answer, respond in this format:
<think>I have completed the logical reasoning and derived the final answer.</think>
[Your final answer here]
""".strip()
SONG_REC_PROMPT = """
你是“听歌识曲” (Aha-Music) Agent。
你的唯一任务是使用浏览器工具集 ${tools_description} 来识别用户提供的音频文件。

### 输入 (Query)
你将收到一个音频文件的名字，例如："song.mp3"。

### 严格的执行流程
你必须严格按照以下顺序执行操作，不要跳过任何步骤：
0. **获取文件绝对路径:**
    * 从用户 query 中获取音频文件名（例如 "song.mp3"）。
    * 使用工具获取该文件的**绝对路径**，以便后续上传使用。*

1.  **导航 (Navigate):**
    * 导航至 "https://aha-music.com/?ref=zhanid.com"

2.  **分析页面 (Snapshot 1):**
    * 调用 `take_snapshot` 获取页面 DOM。
    * 在快照中找到 "Upload a file" 的 `uid`。

3.  **点击上传 (Click):**
    * 调用 `click` 工具，使用上一步找到的 `uid`。

4. **查找上传区域 (Snapshot 2):**
    * 调用 `take_snapshot` 获取页面 DOM。
    * 在快照中找到上传区域的 `uid`。

5.  **上传文件 (Upload):**
    * 调用 `upload_file` 工具。
    * `uid`：使用你找到的上传区域的 `uid`.
    * `filePath`：使用来自用户 query 的**绝对文件路径**。

6.  **等待 1 分钟 (Wait 1):**
    * 文件上传后，你必须等待60秒。
    * 调用 `wait_for_timeout` 工具，设置 `timeout=60000`。

7.  **检查结果 (Snapshot 3):**
    * 调用 `take_snapshot`。
    * 分析快照：
        * **IF** 你看到了歌曲名称 (例如 "Result: [Song Name]")，跳转到**步骤 10**。
        * **IF** 你只看到了 "Processing..."、"Waiting..." 或没有结果，继续**步骤 8**。

8.  **再次等待 1 分钟 (Wait 2):**
    * (如果需要) 调用 `wait_for_timeout` 工具，设置 `timeout=60000`。

9.  **最终检查 (Snapshot 4):**
    * 调用 `take_snapshot`。

10. **提取结果 (Extract):**
    * 分析快照，找到并提取歌曲名称（例如，查找 `role='heading'` 的元素）。

11. **关闭页面 (Close):**
    * 调用 `close_page`。

### 工具调用 (JSON)
当你需要使用工具时，必须且只能使用此 JSON 格式：
```json
{
    "think": "我的思考过程 (例如: '步骤 1: 导航到 aha-music')",
    "tool_name": "[Tool name]",
    "arguments": {
        "[parameter_name]": "[parameter_value]"
    }
}
```
最终答案 (FINISH)
当你成功提取到歌曲名称后，必须以此格式返回： <think>任务完成，已找到歌曲名称。</think> [提取到的歌曲名称] """.strip()
# ----------------- Agent Configuration ----------------------
# preset tools and agents from oxygent


# Plan and Action Parser
plan_parser = PydanticOutputParser(output_cls=Plan)
action_parser = PydanticOutputParser(output_cls=Action)

# Agents
time_agent = oxy.ReActAgent(
    name="time_agent",
    desc="用于时区感知的时间工具，可获取本地时间、时区转换等",
    desc_for_llm="""A timezone-aware time utility toolset.
It can:
1. Retrieve the current local time in a specific timezone.
2. Convert time between different IANA timezones.
Useful for scheduling, time synchronization, and timezone conversions.""",
    tools=["time_tools"],
    llm_model=LLM_MODEL,
)

# 替换前：你现在的 file_agent 描述可能包含 "Cannot list folders"
# 我们替换为允许列目录的描述：

file_agent = oxy.ReActAgent(
    name="file_agent",
    desc="用于文件系统操作：读/写/删/查（包括列目录）",
    desc_for_llm=(
        "Use this agent for file operations: reading, writing, deleting, renaming, checking, and listing files. "
        "It also supports basic file conversions, such as converting a web page (HTML) to an image. "
    ),
    tools=["file_tools"],
    llm_model=LLM_MODEL,
)

# 可选：如果你希望 file_agent 更严格地要求输出工具调用 JSON 格式（便于 executor 解析），
# 可以在 file_agent 的 prompt 中添加一个明确的工具调用模板（不强制，但有助于 LLM）。

math_agent = oxy.ReActAgent(
    name="math_agent",
    desc="用于执行精确的数学运算",
    desc_for_llm="Use this agent to perform precise or safe mathematical operations, like computing pi, doing element-wise list math, or evaluating math expressions.",
    tools=["math_tools"],
    llm_model=LLM_MODEL,
)


python_agent = oxy.ReActAgent(
    name="python_agent",
    desc="用于安全执行短 Python 片段或表达式",
    desc_for_llm="Use this agent to safely execute short Python code snippets or evaluate expressions. It does not run external .py files or system commands.",
    tools=["python_tools"],
    llm_model=LLM_MODEL,
)

shell_agent = oxy.ReActAgent(
    name="shell_agent",
    desc="用于在系统环境中执行完整 shell 命令",
    desc_for_llm="Use this agent to execute full shell commands in the system environment, such as ls, cat, python xxx.py, or bash commands.",
    tools=["shell_tools"],
    llm_model=LLM_MODEL,
)

string_agent = oxy.ReActAgent(
    name="string_agent",
    desc="文本分析与字符串提取工具",
    desc_for_llm="""A set of utilities for text analysis and string extraction tasks. It can extract emails, URLs, and validate formats.""",
    tools=["string_tools"],
    llm_model=LLM_MODEL,
)

system_check_agent = oxy.ReActAgent(
    name="system_check_agent",
    desc="系统检测与资源监控工具",
    desc_for_llm="""A toolset for system inspection and resource monitoring. Retrieve OS, CPU, memory, disk, and Python version info.""",
    tools=["system_tools"],
    llm_model=LLM_MODEL,
)

planner = oxy.ChatAgent(
    name="planner",
    llm_model=LLM_MODEL,
    desc="用于生成复杂任务的多步骤执行计划",
    desc_for_llm="A dedicated agent for generating multi-step, sequential plans in JSON format for complex tasks.",
    prompt=PLANNER_PROMPT,
    func_process_input=update_query
)


analyser = oxy.ReActAgent(
    name="analyser",
    desc="根据意图将查询路由到正确的代理",
    desc_for_llm="Route queries to the right agent based on intent (web, file, image, audio, code, math, sql, etc.). Outputs a single JSON tool call.",
    prompt=ANALYSER_PROMPT,
    llm_model=LLM_MODEL,
    # give analyser access to general LLM but not necessarily to the low-level tools.
    # It only needs to output routing JSON; actual execution will be by the chosen agent.
    sub_agents=[
    "executor",     # 负责所有原子工具调用
    "task_solver",  # 负责所有复杂多步规划
    "logic_agent"
], 
    history_limit=0, #不受历史记录影响
)

firecrawl_agent = oxy.ReActAgent(
    name="firecrawl_agent",
    desc="用于网页抓取和提取结构化内容,还可以基于抓取的数据回答用户查询",
    desc_for_llm = """This agent specializes in **web content retrieval**.  
It can **scrape or crawl a specific, known URL** to extract information,  
or **perform efficient web searches** to find, verify, and summarize the most accurate and up-to-date data.
    """,
    tools=["firecrawl_tools", "webparsec_tools"], # 搭载工具
    prompt = FIRE_CRAWL_PROMPT,
    llm_model=LLM_MODEL,
)
# Master Agent
master = oxy.ReActAgent(
    name="master",
    llm_model=LLM_MODEL,
    prompt=MASTER_PROMPT,
    sub_agents=[analyser.name],
    is_master=True,
    history_limit=0, #不受历史记录影响
)

# Plan and Solve Agent
task_solver = oxy.WorkflowAgent(
    name="task_solver",
    llm_model=LLM_MODEL,
    desc="Solve complex, multi-step tasks using a custom Plan-Execute-Reflect workflow.",
    desc_for_llm="An agent designed to handle complex, multi-step tasks by planning, executing, and reflecting using a custom workflow.",
    func_workflow=plan_and_solve_workflow, # 传入您的自定义函数
    sub_agents=["planner", "executor"], # 声明依赖的 Agent
)


multimodal_agent = oxy.WorkflowAgent(
    name="multimodal_agent",
    llm_model=VLM_MODEL,
    desc="用于多模态理解和分析（图像、视频、PDF、音频）",
    desc_for_llm=(
        "A multimodal agent for understanding and analyzing images, videos, PDFs, and audio files."
    ),
    sub_agents=["file_agent","audio_agent"],
    prompt=VQA_PROMPT,
    func_workflow=vlm_loader_workflow,
)
executor = oxy.ReActAgent(
    name="executor",
    llm_model=LLM_MODEL,
    desc="执行单个步骤，通过选择和调用最合适的工具代理来完成任务",
    desc_for_llm="Executes a single step from the plan by selecting and calling the most appropriate tool agent.",
    sub_agents=executor_subagents_name,    # 声明可调用的子 agent
    prompt=EXECUTOR_PROMPT,
    tools=[],
)
file_reader_agent = oxy.ReActAgent(
    name="file_reader_agent",
    desc="Reads a local file using file_tools and extracts relevant information based on the user's query.",
    desc_for_llm = (
    "Reads a local text-based file using file_tools. "
    "Requires two inputs: a valid file path and a detailed search instruction. "
    "It loads the file content, searches for information relevant to the query, "
    "and returns the most accurate and contextually relevant answer found in the file."
),
    tools=["file_tools"],  #限定只能用 file_tools
    prompt=FILE_READER_PROMPT,
    llm_model=LLM_MODEL,
)
github_agent = oxy.ReActAgent(
    name="github_agent",
    desc="用于与 GitHub 仓库交互和检索信息",
    desc_for_llm="Use this agent to interact with GitHub repositories and retrieve information such as issues, pull requests, commits, and code files.",
    tools=["github_h_tools","github_tools"],
    llm_model=LLM_MODEL,
)
stock_agent = oxy.ReActAgent(
    name="stock_agent",
    desc="用于股票数据查询和分析",
    desc_for_llm="Use this agent to query stock market data. "
                 "NOTE: Querying historical prices requires a stock 'code' (e.g., '09618'), not a company name.",
    tools=["stock_tools","bailian_web_search_tools"],
    prompt=STOCK_PROMPT,
    llm_model=LLM_MODEL,
)
audio_agent = oxy.ReActAgent(
    name="audio_agent",
    desc="用于音频文件的分析和处理",
    desc_for_llm="Use this agent to analyze and process audio files, including transcription, sentiment analysis, and audio feature extraction.",
    tools=["audio_tools"],
    llm_model=LLM_MODEL,
)
browser_agent = oxy.ReActAgent(
    name="browser_agent",
    desc="用于自动化浏览器操作和网页交互",
    desc_for_llm="Use this agent to perform automated browser operations and web interactions, such as navigating pages, clicking elements, and filling forms. When using it, you must provide both the task objective and the target webpage URL.",
    tools=["chrome_devtools"],
    sub_agents=["multimodal_agent"],
    llm_model=LLM_MODEL,
    prompt = BROWSER_PROMPT,
)
search_agent = oxy.ReActAgent(
    name="search_agent",
    desc="用于执行网络搜索任务",
    desc_for_llm="Use this agent to perform web search tasks using multiple search engines and aggregate results.",
    tools=["baidu_search_tools","bailian_web_search_tools"],
    llm_model=LLM_MODEL,
    prompt = SEARCH_PROMPT,
)
logic_agent = oxy.ReActAgent(
    name="logic_agent",
    desc="用于解决纯粹的逻辑谜题、归纳问题和需要简单计算的推理任务",
    desc_for_llm="Use this agent for pure reasoning, logic puzzles, or riddles (intent_label: logic_puzzle). This agent can use math_agent for calculations but has no other tools.",
    llm_model=LLM_MODEL, #
    prompt=LOGIC_PROMPT,
    sub_agents=["math_agent"], 
    tools=[]
)
browser_VLM_PLANNER = oxy.ChatAgent(
    name="browser_VLM_PLANNER",
    desc="（VLM 大脑）分析浏览器截图并决定下一步的自然语言操作。", #
    llm_model=VLM_MODEL, #
    prompt=VLM_PLANNER_PROMPT,
    tools=[]
)
browser_executor = oxy.ReActAgent(
    name="browser_executor",
    desc="（机械手） 强制执行 VLM 的单一指令并返回截图路径。",
    func_workflow=executor_workflow,
    tools=["chrome_devtools"], # 作为工具被调用
    llm_model=LLM_MODEL,
    prompt=BROWSER_EXECUTOR_PROMPT,
)

visual_browser_workflow_agent = oxy.WorkflowAgent(
    name="visual_browser_workflow_agent",
    desc="（工作流）使用 VLM 视觉循环来执行复杂的浏览器任务。",
    desc_for_llm="（工作流）使用 VLM 视觉循环来执行复杂的浏览器任务。",
    func_workflow=visual_browser_workflow, 
    llm_model=LLM_MODEL, 
    sub_agents=[
        "browser_VLM_PLANNER", 
        "browser_executor" 
    ]
)

song_recognition_agent = oxy.ReActAgent(
    name="song_recognition_agent",
    desc="Song Recognition: Input an absolute audio file path, use aha-music.com to identify it, and output the song name.",
    desc_for_llm="""
    [Song Recognition Agent]
    Input: An absolute path to an audio file (e.g., .mp3, .wav) (e.g., "D:\\temp\\audio.mp3").
    Output: The recognized song name (string).
    """.strip(),
    tools=["chrome_devtools"],  # 确保 chrome_devtools 已在 oxy_space 中注册
    sub_agents=["file_agent"],  # 如果需要文件读取功能，可以添加 file_agent
    llm_model=LLM_MODEL,      # 使用您在 all_agents.py 中定义的 LLM_MODEL
    prompt=SONG_REC_PROMPT
)