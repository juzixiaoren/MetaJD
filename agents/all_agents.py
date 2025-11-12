# all_agent.py
import asyncio, os
from oxygent import MAS, oxy,Config,preset_tools
import re
import glob
from oxygent.schemas.oxy import OxyRequest, OxyResponse, OxyState
import dotenv
from pydantic import BaseModel, Field
from typing import List, Union
from oxygent.utils.llm_pydantic_parser import PydanticOutputParser # 导入解析器
import json
import sys
from typing import Any, List, Optional, Type, Union

executor_subagents_name = [#执行器可用的子代理列表
    "baidu_search_agent",
    "python_agent",
    "file_agent",
    "math_agent",
    "string_agent",
    "system_check_agent",
    "firecrawl_agent",
    "bailian_web_search_agent",
    "github_agent",
    "multimodal_agent",
    "stock_agent"
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
        # 2.3 重规划/反思 (如果启用)
        replan_query = f"""
        The user's original objective was: {original_query}
        The current step history is: {past_steps}
        The remaining plan is: {plan_steps[1:]}

        Please analyze the situation based on the 'step history'. 
        -If the objective has been fully and accurately achieved, matches the original input, and the remaining steps cannot further improve the precision of the answer, then use the Response action to output the final answer, strictly adhering to the original formatting and language requirements. 
        - Otherwise, update the Plan action with the next logical step(s) based on the history and remaining plan, following the Core Planning Rules (especially the search fallback rule if applicable).
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
                raise Exception("LLM 返回的响应中未找到 JSON。")
            action_data = action_parser.parse(json_string)
        except Exception as e:
            return OxyResponse( 
            state=OxyState.FAILED,
            output=f"重规划 Agent 返回格式错误: {e}\n原始输出: {replanner_response.output}")

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
    工作流 (VLM Loader v13 - 改进版)：
    1.  提取文本查询。
    2.  提取文件名 (pdf, jpg, png, mp4, mp3)。
    3.  调用 file_agent 查找文件路径。
    4.  分析文件类型：
        a. PDF -> 转换为图像 -> 调用 VLM。
        b. MP4 -> 智能抽帧（动态决定策略）-> 调用 VLM。
        c. 图像 -> 直接调用 VLM。
        d. MP3 -> 调用 audio_agent。
    5.  增加中间过程输出，便于调试。
    """

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

    print(f"[VLM工作流] 步骤1: 提取的文本查询: {text_query}")

    # --- 2. 提取文件名 ---
    filename_match = re.search(r"['\"]?([\w\-\.]+\.(pdf|jpg|png|jpeg|mp4|mp3))['\"]?", text_query, re.IGNORECASE)
    if not filename_match: return OxyResponse(state=OxyState.FAILED, output=f"VLM工作流错误：在查询 '{text_query}' 中未找到有效的文件名 (e.g., pdf, jpg, mp4, mp3)。")
    filename = filename_match.group(1)
    file_ext = filename.split('.')[-1].lower()

    print(f"[VLM工作流] 步骤2: 提取的文件名: {filename}, 扩展名: {file_ext}")

    # --- 3. 查找文件路径 ---
    find_file_query = f"请递归查找文件 '{filename}' 并返回第一个匹配的绝对路径"
    find_resp = await oxy_request.call(callee="file_agent", arguments={"query": find_file_query})

    # --- 4. 解析文件路径 ---
    file_path = ""
    output_str = ""
    if isinstance(find_resp.output, list):
        if len(find_resp.output) > 0: output_str = str(find_resp.output[0])
        else: return OxyResponse(state=OxyState.COMPLETED, output=f"文件 '{filename}' 未找到 (file_agent 返回了空列表)。")
    elif isinstance(find_resp.output, str): output_str = find_resp.output
    else: return OxyResponse(state=OxyState.FAILED, output=f"file_agent 返回了意外的类型: {type(find_resp.output)}")

    path_match = re.search(r"([A-Za-z]:\\[^\]\s,\"\*`]+)|(/[^\]\s,\"\*`]+)", output_str)

    if path_match:
        file_path = path_match.group(0).strip("'\"`* ")
    else:
         return OxyResponse(
            state=OxyState.COMPLETED,
            output=f"文件 '{filename}' 未找到 (在 '{output_str}' 中解析路径失败)。"
        )

    print(f"[VLM工作流] 步骤3: 找到文件路径: {file_path}")

    # --- 5. 根据文件类型处理 ---

    if file_ext == 'mp3':
        print(f"[VLM工作流] 步骤4: 检测到音频文件，调用 audio_agent")

        combined_query = f"""
        User Query: {text_query}
        File Path: {file_path}
        """

        audio_resp = await oxy_request.call(
            callee="audio_agent",
            arguments={
                "query": combined_query
            }
        )
        return audio_resp

    attachment_paths = []

    if file_ext == 'pdf':
        print(f"[VLM工作流] 步骤4: 检测到PDF文件，开始转换为图像")
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

        print(f"[VLM工作流] PDF转换完成，生成了 {len(attachment_paths)} 张图像")

    elif file_ext == 'mp4':
        print(f"[VLM工作流] 步骤4: 检测到视频文件，开始智能抽帧")

        # 步骤4.1: 先获取视频信息
        video_info_query = f"请使用 get_video_info 工具获取此视频的元信息: {file_path}"
        video_info_resp = await oxy_request.call(
            callee="file_agent",
            arguments={"query": video_info_query}
        )

        print(f"[VLM工作流] 视频信息: {video_info_resp.output}")

        # 步骤4.2: 检测用户查询中是否包含时间信息
        time_pattern = r'第?\s*(\d+\.?\d*)\s*秒|(\d+\.?\d*)\s*-\s*(\d+\.?\d*)\s*秒|(\d+\.?\d*)\s*到\s*(\d+\.?\d*)\s*秒'
        time_matches = re.findall(time_pattern, text_query)

        timestamps = []
        if time_matches:
            print(f"[VLM工作流] 检测到时间信息: {time_matches}")
            for match in time_matches:
                # match = (single_time, start_time, end_time, start_time2, end_time2)
                if match[0]:  # 单个时间点
                    timestamps.append(float(match[0]))
                elif match[1] and match[2]:  # 时间范围（格式1: X-Y秒）
                    start = float(match[1])
                    end = float(match[2])
                    # 在范围内每0.5秒采样一次
                    current = start
                    while current <= end:
                        timestamps.append(current)
                        current += 0.5
                elif match[3] and match[4]:  # 时间范围（格式2: X到Y秒）
                    start = float(match[3])
                    end = float(match[4])
                    # 在范围内每0.5秒采样一次
                    current = start
                    while current <= end:
                        timestamps.append(current)
                        current += 0.5

        # 步骤4.3: 根据是否有时间戳信息，选择不同的抽帧策略
        if timestamps:
            print(f"[VLM工作流] 使用基于时间戳的精确抽帧: {timestamps}")
            # 使用时间戳抽帧工具
            timestamp_str = str(timestamps)
            smart_frame_query = f"""
            请使用 extract_frames_by_timestamps 工具从视频中提取特定时间点的帧：

            视频路径: {file_path}
            时间戳列表: {timestamp_str}
            输出目录: 'temp_data/video_frames'
            时间窗口: 0.5 秒

            请调用工具并返回所有提取的帧文件的绝对路径列表。
            """
        else:
            print(f"[VLM工作流] 使用智能抽帧策略")
            # 使用智能抽帧策略
            smart_frame_query = f"""
            请为以下视频文件进行智能关键帧提取：

            视频路径: {file_path}
            视频信息: {video_info_resp.output}
            用户查询: {text_query}

            任务要求：
            1. 根据视频时长和FPS，智能决定抽帧策略：
               - 如果视频较短（<30秒），提取更密集的帧（例如每秒2-3帧）
               - 如果视频较长（>60秒），提取关键帧（例如每3-5秒1帧）
            2. 使用 extract_frames 工具提取帧，并保存到 'temp_data/video_frames' 目录
            3. 返回所有提取的帧文件的绝对路径列表

            请你根据视频信息，自主决定最佳的 frame_interval 参数。
            """

        convert_resp = await oxy_request.call(
            callee="file_agent",
            arguments={"query": smart_frame_query}
        )

        # 解析抽帧结果
        if isinstance(convert_resp.output, list):
            attachment_paths = convert_resp.output
        elif isinstance(convert_resp.output, str):
            if "Error:" in convert_resp.output:
                return OxyResponse(state=OxyState.FAILED, output=f"视频抽帧失败: {convert_resp.output}")
            # 尝试从输出中提取图像路径
            attachment_paths = re.findall(r"([A-Za-z]:\\[^\]\s,\"\*]+\.(png|jpg))|(/[^\]\s,\"\*]+\.(png|jpg))", str(convert_resp.output))
            attachment_paths = [p[0] or p[2] for p in attachment_paths if p[0] or p[2]]

        # 如果没有成功提取到路径，尝试直接读取目录
        if not attachment_paths:
            frames_dir = "temp_data/video_frames"
            try:
                attachment_paths = sorted(glob.glob(f"{frames_dir}/*.jpg") + glob.glob(f"{frames_dir}/*.png"))
            except Exception as e:
                print(f"[VLM工作流] 警告: 无法读取帧目录: {e}")

        print(f"[VLM工作流] 视频抽帧完成，提取了 {len(attachment_paths)} 帧")
        print(f"[VLM工作流] 关键帧路径: {attachment_paths[:5]}...")  # 只显示前5个

    else:
        # 5c. 如果是图像 (jpg, png)，直接使用
        print(f"[VLM工作流] 步骤4: 检测到图像文件，直接使用")
        attachment_paths = [file_path]

    if not attachment_paths:
        return OxyResponse(state=OxyState.FAILED, output=f"处理文件 '{file_path}' 失败，未能获取 VLM 可分析的图像。")

    print(f"[VLM工作流] 步骤5: 准备调用VLM，共 {len(attachment_paths)} 张图像")

    # --- 6. 可选：对提取的帧进行OCR预处理（使用VLM进行文字识别）---
    ocr_texts = []
    if file_ext == 'mp4' and len(attachment_paths) > 0:
        print(f"[VLM工作流] 步骤5.5: 对关键帧进行OCR预处理 (使用VLM)")
        for i, img_path in enumerate(attachment_paths[:10]):  # 最多处理前10帧
            try:
                print(f"[VLM-OCR] 正在处理帧 {i+1}: {img_path}")

                # 直接调用 VLM 进行 OCR（不再通过 file_agent）
                ocr_prompt = (
                    "请提取图像中的所有可见文字，包括中文、英文、数字和符号。"
                    "按从上到下、从左到右的顺序输出所有文字内容，每行文字单独一行。"
                    "如果没有文字，输出'No text detected.'"
                )

                ocr_messages = [{
                    "role": "user",
                    "content": [
                        {"type": "image_url", "image_url": {"url": img_path}},
                        {"type": "text", "text": ocr_prompt}
                    ]
                }]

                ocr_resp = await oxy_request.call(
                    callee=VLM_MODEL,
                    arguments={"messages": ocr_messages}
                )

                if isinstance(ocr_resp.output, str) and ocr_resp.output.strip():
                    extracted_text = ocr_resp.output.strip()
                    if extracted_text.lower() != "no text detected.":
                        ocr_texts.append(f"帧{i+1}的文字: {extracted_text}")
                        print(f"[VLM工作流] 帧{i+1} OCR结果: {extracted_text[:100]}...")
                    else:
                        print(f"[VLM工作流] 帧{i+1} 未检测到文字")
            except Exception as e:
                print(f"[VLM工作流] 帧{i+1} OCR失败: {e}")

    # --- 7. 构建VLM分析提示 ---
    vlm_meta_query = f"""
    [原始用户请求]: "{master_query}"

    [你的任务]: 你是一个精确的多模态分析助手。请严格按照以下步骤操作：

    1.  **视觉分析 (内部思考):** 首先，全面分析附加的图像（们），找到与 [原始用户请求] 相关的所有信息。

    2.  **约束分析 (内部思考):** 其次，仔细重读 [原始用户请求]，找出其中所有的*约束条件*。例如：
        * 是否要求特定*数量*？（例如："一个"，"多少个"）
        * 是否要求特定*格式*？（例如："仅输出数值"，"仅输出文字"）
        * 是否有*筛选条件*？（例如："最显眼的"，"没有百亿补贴的"）

    3.  **文字识别辅助:** 以下是通过OCR提取的文字信息，可以作为辅助参考：
    {chr(10).join(ocr_texts) if ocr_texts else "无OCR文字"}

    4.  **生成答案 (最终输出):** 综合视觉分析和OCR文字信息，应用第 2 步中分析出的*约束条件*，生成最终的、精确的答案。

    [输出要求]:
    - 严格遵守 [原始用户请求] 中的所有格式要求
    - 如果要求"仅输出数值"，就只返回数字，不要添加任何解释
    - 如果要求"仅输出文字"，就只返回文字内容，不要添加描述
    - 请确保答案的准确性，优先使用OCR识别的文字信息
    """

    content_list = []
    for img_path in attachment_paths:
        content_list.append({ "type": "image_url", "image_url": { "url": img_path } })

    content_list.append({ "type": "text", "text": vlm_meta_query })

    vlm_messages = [{"role": "user", "content": content_list}]

    print(f"[VLM工作流] 步骤6: 开始调用VLM模型进行分析")

    vlm_response = await oxy_request.call(
        callee=VLM_MODEL,
        arguments={ "messages": vlm_messages }
    )

    print(f"[VLM工作流] 步骤7: VLM分析完成")
    print(f"[VLM工作流] 最终结果: {vlm_response.output[:200]}...")

    return vlm_response
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
  2:Verify that any user-provided attachments have correct filenames, and automatically fix them if needed (e.g., if the user provides XXX,mp3, you should correct it to XXX.mp3).

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
  2.  You **MUST** perform the final screening/filtering on this `Observation` content.
  3.  Your output MUST be **short and direct**, containing only the **core entity or fact** asked for (e.g., "巴黎", "木星", "4").
  4.  You **MUST NOT** output the `think` tag or any JSON.
  5.  Avoid redundant phrasing like "答案是xx" — return **only** the essential answer.

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
      "query": "<user_query> The files name is:[ <list_of_attachment_paths_from_input> ] ",
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
- **baidu_search_agent**: Use this agent to perform information retrieval using Baidu search tools.
- **file_agent**: Responsible for all file-related operations, including reading, writing, conversion, and content extraction. Supports multiple file formats such as text, CSV, and PDF (PDF only supports text extraction).
- **math_agent**: Performs safe mathematical computations, like arithmetic or evaluating expressions.
- **string_agent**: Provides text analysis utilities — extract emails, URLs, or validate formats.
- **system_check_agent**: Inspects system info — OS, CPU, memory, disk, Python version.
- **firecrawl_agent**: This agent specializes in **web content retrieval**.  It can **scrape or crawl a specific, known URL** to extract information,  or **perform efficient web searches** to find, verify, and summarize the most accurate and up-to-date data.
- **bailian_web_search_agent**: Use this agent to perform efficient web searches and content retrieval using the Aliyun Dashscope search tool.
- **github_agent**: Use this agent to interact with GitHub repositories and retrieve information such as issues, pull requests, commits, and code files.(When use it,please give the url of the repo)
- **multimodal_agent**: Use this agent to analyze and understand content from images, audio, video, or PDFs.
- **stock_agent**: Use this agent to query stock market data. NOTE: Querying historical prices requires a stock 'code' (e.g., '09618'), not a company name.
## Core Planning Rules
1. **Tool-First Principle (NEW):**
   - You **MUST** prioritize specialized agents (like `stock_agent`, `github_agent`) over generic web search (`bailian_web_search_agent`, `firecrawl_agent`) when a query directly matches their capability (e.g., stock price queries, GitHub issue analysis).
   - Only use generic web search (Rule 5) if the specialized agent fails or if you need preparatory information (like finding a stock 'code' before calling `stock_agent`).

    1b. **Agent-Aware but Neutral** — Use agent descriptions to understand possible operations...
2. **No Human Simulation** — Never include steps like "click the link" or "read manually".
3. **Web Content Retrieval** — If a plan involves webpage data:
   (1) Search for the target webpage’s URL using complete, original keywords from the user’s query — do not omit or simplify any keyword.
   (2) If the query is simple or clear, directly search using the **original sentence** instead of fragmenting it into smaller parts.
   (3) Once a candidate webpage is found, crawl that webpage to extract the needed content or elements.
   (4) If a web content retrieval task involves visual-related elements (such as the shape, color, or layout of webpage components),
    the file_agent should be used to convert the HTML page into an image(need webpage URL).
    It takes the webpage URL as input and returns the generated image filename.
    After that, a multimodal agent should be used to perform the visual analysis and understanding of the image.
4. **Multimodal Task Logic**
   - If multimodal analysis is required (e.g., analyzing images, audio, video,PDF, or converted HTML screenshots),
     the planner must:
     1. Pass the **complete task content** and the **exact local file name** as inputs.
     2. Ensure that the multimodal agent only analyzes **local files**, not remote URLs.
5. **Search Logic**
    - When performing web information queries or retrieving webpage URLs, use both bailian_web_search_agent and baidu_search_agent to obtain search results.
    - Conduct cross-verification and consistency checking between the two sources, comparing the credibility, relevance, and completeness of the information, and combine their findings to form a comprehensive understanding of the answer. (Divide this process into 2 steps in the plan.)
    - After integration, if the obtained information is missing, vague, or uncertain, then use firecrawl_agent as the final fallback option to perform deeper or real-time web crawling to ensure accurate and up-to-date data.
6. **PPT Processing Logic**
- When the user query involves **ppt** or **pptx** files:
    1. Use the `file_agent` to **convert any `.ppt` file into `.pptx`** format to ensure compatibility.
    2. Then use the `file_agent` again to **convert the `.pptx` file into images** (one image per slide if possible).
    3. Pass the **generated image files paths** to the `multimodal_agent` for further analysis or reasoning.
- The multimodal analysis should be based on the **converted images**, not directly on the `.pptx` file itself.
7. **Preserve Detail** — Keep all important conditions from the user's question (e.g., “as of 2025”, “top 10”, “world record”).
8. **Context Preservation (File Paths):** When a plan involves multiple steps operating on the same file or directory (e.g., Step 1: "create dir `a/b/c`", Step 2: "write file in `c`"), the subsequent steps **MUST** use the *full, absolute, or relative path* from the previous step.
    * (错误示例): Step 1: "create `test_dir/subdir1/subdir2`". Step 2: "write to `subdir2`".
    * (正确示例): Step 1: "create `test_dir/subdir1/subdir2`". Step 2: "write file to `test_dir/subdir1/subdir2/test.txt`".
9. **Language Consistency** — Make sure the plan uses the same language as the user query, unless the user explicitly requests output in another language.
Note: If the user only asks to use English punctuation, that does not mean the output should be in English.

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
BAIDU_PROMPT="""
Additional Behavior Rules:

After retrieving search results, compare them carefully with the user’s query.

If the retrieved results are uncertain or ambiguous, explicitly state that the information may not be fully accurate.

In such cases, return as many relevant possible answers as you can, sorted from most to least likely, in the following format:

Possible answers (likelihood decreasing):
{Answer 1: ...}
{Answer 2: ...}
...

If the query involves a specific website or webpage that cannot be accessed directly, perform a search for that website’s URL instead.

Return the most relevant possible URLs and their short introductions, ordered by relevance.
Example:

Query: "JD Health homepage"
Most relevant results:
{Result 1: https://www.jdh.com/, Description: ...}
{Result 2: https://health.jd.com/, Description: ...}

If you believe the retrieved information might be incorrect or unreliable,
search for the **official website URL** of the company, organization, or information source mentioned in the original query,
and **include that official URL in your final answer** to help the user verify the information.

""".strip()
BAILIAN_PROMPT="""
After retrieving search results, analyze them with semantic understanding rather than simple keyword matching.

If the retrieved results are uncertain, incomplete, or conflicting, clearly explain the potential inaccuracy.

In such cases, summarize and return multiple possible answers ranked by confidence level, using the following format:

Possible answers (confidence decreasing):
{Answer 1: ...}
{Answer 2: ...}
...

If the query relates to a specific website, page, or online source that cannot be directly accessed, perform a search for that site's URL or relevant entry points instead.

If no reliable answer is found, explicitly state that no trustworthy result was obtained.  
If the information might exist on an official website, search for that official page’s URL and include it in your response.  
Finally, suggest using other tools to continue the search.

Example:

Query: "JD Health homepage"
Most relevant results:
{Result 1: https://www.jdh.com/, Description: ...}
{Result 2: https://health.jd.com/, Description: ...}
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
STOCK_PROMPT = """
You are a professional stock data query assistant.
Your task is to, based on the user's request, call the appropriate tool to fetch stock information.

## Available tools
${tools_description}):

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
    desc="用于文件系统操作和多媒体处理：读/写/删/查/视频抽帧/图像OCR",
    desc_for_llm=(
        "Use this agent for file operations and multimedia processing: "
        "1. File operations: reading, writing, deleting, renaming, checking, and listing files. "
        "2. Video processing: get video info, extract frames from videos. "
        "3. Image processing: OCR text extraction, image analysis. "
        "4. File conversions: PDF to images, HTML to images, etc."
    ),
    tools=["file_tools", "video_tools", "image_tools"],
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

baidu_search_agent = oxy.ReActAgent(
    name="baidu_search_agent",
    desc="通过百度 API 执行网络搜索并返回相关内容",
    desc_for_llm="Use this agent to search information on the web through Baidu API and retrieve online content or answers.",
    tools=["baidu_search_tools"],
    llm_model=LLM_MODEL,
    additional_prompt=BAIDU_PROMPT,
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

baidu_search_agent = oxy.ReActAgent(
    name="baidu_search_agent",
    llm_model=LLM_MODEL,
    desc="使用百度搜索工具进行信息检索",
    desc_for_llm="""Use this agent to perform information retrieval using Baidu search tools.""",
    tools=["baidu_search_tools"],
    additional_prompt=BAIDU_PROMPT,
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
bailian_web_search_agent = oxy.ReActAgent(
    name="bailian_web_search_agent",
    desc="使用阿里云百炼搜索工具进行高效的网络搜索和内容检索",
    desc_for_llm="""Use this agent to perform efficient web searches and content retrieval using the Aliyun Dashscope search tool.""",
    tools=["bailian_web_search_tools"],
    additional_prompt=BAILIAN_PROMPT,
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