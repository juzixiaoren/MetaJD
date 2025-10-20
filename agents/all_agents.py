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

executor_subagents_name = [#执行器可用的子代理列表
    "baidu_search_agent",
    "http_agent",
    "python_agent",
    "file_agent",
    "math_agent",
    "string_agent",
    "system_check_agent",
    "firecrawl_agent",
    "file_reader_agent",
]

available_agent_desc = "\n".join([#可用子代理描述
    f"- **{a}**: {getattr(globals()[a], 'desc_for_llm', 'No description provided.')}"
    for a in executor_subagents_name
    if a in globals()
])


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
    max_replan_rounds = 5 # 限制循环次数
    
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
        task_formatted = f"We have finished the following steps: {past_steps}\nThe current step to execute is: {task}"
        executor_response = await oxy_request.call(
            callee="executor", 
            arguments={"query": task_formatted}
        )
        
        # 2.2 更新历史
        past_steps += f"\nTask: {task}, Result: {executor_response.output}"
        
        # 2.3 重规划/反思 (如果启用)
        replan_query = f"""
        The user's original objective was: {original_query}
        The current step history is: {past_steps}
        The remaining plan is: {plan_steps[1:]}

        Please analyze the situation. If the task is completed, use the Response action. Otherwise, update the Plan.
        """
        
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
        callee=oxy_request.llm_model, 
        arguments={"query": summary_query}
    )
    
    return summary_response

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

    ### Objective
    Your only job is to route *all* non-greeting queries to the `analyser` agent.
    You **never** solve tasks directly.

    ---

    ### ⚙️ Behavior Rules
    1.  If the user message is a simple greeting (e.g., "hi", "hello", "你好"), respond briefly.
    2.  If you call `analyser` and the Observation **is NOT** a JSON tool call, it's the final answer. You **MUST** output the Observation content **EXACTLY** as received and terminate.
    3.  For any other message, you **MUST** call the `analyser` tool using the exact format below.

    ---

    ### Tool Call Format
    You must respond **only** with the following exact JSON object format, and nothing else:
    ```json
    {
        "think": "Routing user query to the core analyser.",
        "tool_name": "analyser",
        "arguments": {
            "query": "<user_query>"
        }
    }
    ## Examples
    User: hi Assistant: Hello!

    User: 京东金融提供了哪些服务？ Assistant:
    JSON

    {
        "think": "Routing user query to the core analyser.",
        "tool_name": "analyser",
        "arguments": {
            "query": "京东金融提供了哪些服务？"
        }
    }
    """.strip()

# Plan Agent
PLANNER_PROMPT = """
You are part of a multi-agent system. Other agents will execute your planned steps sequentially.
Your goal is to translate a complex user request into a clear, step-by-step list for execution.

## Core Planning Rules
1. **Tool-Centric** — Each step must be assigned to a specific agent or tool (e.g., `baidu_search_agent`, `firecrawl_agent`, `python_agent`).
2. **No Human Simulation** — Never plan steps like "click the link" or "read manually". Use `http_agent` or `firecrawl_agent` for web data.
3. **Preserve Detail** — Include all important conditions from the user's query (e.g., "as of 2025", "top 10", "world record").
4. **Language Consistency** — All step instructions must match the user's query language.

## Available Agents and Descriptions
{available_agent_desc}

## Output Format
Your output must strictly match the following JSON Schema. Only output the JSON object with no explanations or markdown fences.

{format_instructions}

**Do not include explanations, reasoning text, or markdown syntax outside the JSON object.
""".format(
    format_instructions=PydanticOutputParser(output_cls=Plan).format_string,
    available_agent_desc=available_agent_desc
).strip()


EXECUTOR_PROMPT = """
You are the Executor Agent. Your job is to execute one single task by calling the correct sub-agent.

# Behavior Rules
1. Read the task assigned to you.
2. Choose the one most appropriate agent from your available sub-agents.
3. Pass the task instruction directly to that agent.
4. Do NOT plan, modify the task, or execute multiple steps yourself.

# Output Format 1 (Your *only* action)
You must respond only with the following exact JSON object format:
JSON
{
    "think": "我需要执行任务: [Your task description]. 最合适的代理是 [Agent Name]。",
    "tool_name": "[Agent Name]",
    "arguments": {
        "query": "[Full instruction or query for the sub-agent]"
    }
}

# Examples
User Task: "find the fastest bird in the world"
Response JSON:
{
    "think": "我需要执行任务: 找出世界上最快的鸟类。最合适的代理是百度搜索代理。",
    "tool_name": "baidu_search_agent",
    "arguments": {
        "query": "世界上最快的鸟类是什么"
    }
}

# Output Format 2: Handling Tool Results
After receiving the tool result:
1. Check if the result fully satisfies the user's query, including all required details, order, and formatting.
2. If the result is complete and accurate, respond in the normal final answer format:
<think>我已经执行了任务并收到了结果。我的工作已经完成。将结果返回给计划者。</think> [The plain text result from the tool]

3. If the result is incomplete, inaccurate, or does not strictly follow the user's instructions (e.g., missing items, wrong order, ambiguous wording):
- DO NOT return it directly to the user.
- Instead, mark the task as complex / multi-step and indicate that it needs to be re-planned or handled by a multi-step solver (task_solver), while keeping the original query intact:
<think>工具返回的结果不完整或不准确。该任务需要多步处理，由 task_solver 重新规划以获得精确答案。</think> [Return the full original user query unchanged]

# Notes
- Always preserve the user's original query in the output.
- Never attempt to guess or manually correct incomplete results.
- All outputs, including "think" and final answers, must be in the same language as the user's query.
""".strip()
FIRE_CRAWL_PROMPT = """
You are the **Firecrawl Agent**, a specialized web-crawling assistant.
You have access to the following tools:
${tools_description}
Your specific job is to:
1. Crawl a given URL.
2. Save the crawled content to a local file.
3. Return ONLY the path to the saved file.

You **MUST** follow these steps sequentially.
Your file's base directory is `./data/web`.
Your file's name must be unique, e.g., `crawl_{uuid.uuid4()}.txt`.
---
### Important Instructions & Workflow

1.  **Receive Task:** You will receive a query, typically containing a URL to crawl (e.g., "crawl https://example.com").
2.  **First Tool Call To crawl web:** You **MUST** first call tools to get the web page content. Use Output Format 1.
3.  **Observe Content:** You will receive the crawled content as an Observation.
4.  **Generate Filename:** Think of a unique filename to save the content (e.g., `crawl_{uuid.uuid4()}.txt`). Ensure it's in an accessible directory.
5.  **Second Tool Call :** You **MUST** then call tools to write the *observed content* to the *generated filename*. Use Output Format 1 again. Construct the query argument carefully, like query = f"write file './data/web/{filename}' content '{crawled_content}'".
6.  **Observe Save Path:** You will receive confirmation and the saved file path as an Observation from tools.
7.  **Final Answer (Return Path):** Your job is now complete. You **MUST** immediately return **ONLY** the file path using Output Format 2.

---
### Output Format 1: Tool Call

When you need to use a tool, you must respond **only** with the following exact JSON object format:
```json
{
    "think": "Your reasoning for this specific tool call (e.g., 'Calling "Tool name" to get content.' or 'Calling "Tool name" to save the crawled content to path "base_directory".')",
    "tool_name": "Tool name",
    "arguments": { "parameter_name": "parameter_value" }
}

### Output Format 2: Final Answer (After saving the file)
After you have successfully called file_agent and received the confirmation/path, you MUST respond in this format (and this format only):

<think>Successfully crawled the URL and saved the content using file_agent. Returning the file path now.</think>  [The plain text file path returned by file_agent, e.g., "./local_file/crawl_abc.txt"]

Do NOT attempt to read the file content yourself. Your only goal is to crawl, save, and return the path.
Tools for querying time can be obtained through retrieval tools. ${additional_prompt}
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

multimodal_agent: for analyzing images, audio, video, or PDFs (multimedia)

master: for greetings or fallback (fallback)

# Routing Rules:

1. Simple Single-Step Task (intent_label: atomic_tool)
   - Route to: executor
   - Description: The task can be completed with a single tool action.
   - Examples: calculate, read file, search, check current time.

2. Complex Multi-Step Task (intent_label: multi_step)
   - Route to: task_solver
   - Description: The task requires multiple steps or sequential reasoning.
   - Examples: "search A then calculate B", "compare A and B", "API retry needed", ambiguous queries.

3. Multimedia Task (intent_label: multimedia)
   - Route to: multimodal_agent
   - Description: The task requires analyzing images, audio, video, or PDF content.

4. Greeting / Fallback (intent_label: fallback)
   - Route to: master
   - Description: The intent is unclear or cannot be mapped to other categories.
"""
FILE_READER_PROMPT = """
You are the File Reader Agent.

Your job:
1. Call the tool `file_tools` to read a local file as requested by the user.
2. Understand the user’s query or search instruction.
3. Extract or summarize the most relevant information from the file content.
4. After reading and analysis, return the result to the user.

### Behavior Rules
1. You may only use the tool `file_tools` for this task.
2. You must call `file_tools` first and wait for the result before answering.
3. Once you receive file content, do not call any other tool.
4. If the user’s query mentions a keyword, section, or pattern, search for it within the file content.
5. Your reply must be concise, relevant, and in the same language as the user’s query.
6. If the file is too long, summarize only the parts that are relevant to the query.
7. If the file cannot be read or the path is invalid, respond with an error message.

### Tool Call Format
When you call `file_tools`, you must output exactly a JSON object formatted as follows (and nothing else):
```json
{
  "think": "explanation of why you call file_tools",
  "tool_name": "file_tools",
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

file_agent = oxy.ReActAgent(
    name="file_agent",
    desc="用于文件系统操作：读/写/删/查",
    desc_for_llm="Use this agent for file system operations: reading, writing, deleting, renaming, or checking if files exist. Cannot list folders or execute code.",
    tools=["file_tools"],
    llm_model=LLM_MODEL,
)

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
)

http_agent = oxy.ReActAgent(
    name="http_agent",
    desc="用于 HTTP 请求（GET/POST），与外部 API 交互",
    desc_for_llm="""This agent is designed to execute HTTP network requests, primarily using GET and POST methods to interact with external APIs or web resources. Returns JSON including status and content.""",
    tools=["http_tools"],
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
    "multimodal_agent" # 负责多模态分析
], 
    history_limit=0, #不受历史记录影响
)

firecrawl_agent = oxy.ReActAgent(
    name="firecrawl_agent",
    desc="用于网页抓取和提取结构化内容,调用文件代理保存结果",
    desc_for_llm = """This agent crawls web pages using Firecrawl, scrapes and extracts structured data from given URLs, 
    and automatically saves the extracted results to local files. 
    It returns the absolute file path of the saved data.""",
    tools=["firecrawl_tools","file_tools"], # 搭载工具
    prompt = FIRE_CRAWL_PROMPT,
    llm_model=LLM_MODEL,
)

baidu_search_agent = oxy.ReActAgent(
    name="baidu_search_agent",
    llm_model=LLM_MODEL,
    desc="使用百度搜索工具进行信息检索",
    desc_for_llm="Use this agent to perform information retrieval using Baidu search tools.",
    tools=["baidu_search_tools"],
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

# VLM and Multimodal Agent
multimodal_vlm = oxy.HttpLLM(
    name=VLM_MODEL,
    api_key=get_env_var("DEFAULT_VLM_API_KEY"),
    base_url=get_env_var("DEFAULT_VLM_BASE_URL"),
    model_name=get_env_var("DEFAULT_VLM_MODEL_NAME"),
    is_multimodal_supported=True, # 启用多模态支持
    llm_params={"temperature": 0.1},
)

multimodal_agent = oxy.ChatAgent(
    name="multimodal_agent",
    llm_model=VLM_MODEL, # 使用 VLM
    desc="Analyze and extract information from image, audio, video, or PDF attachments. Use this for file content understanding.",
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