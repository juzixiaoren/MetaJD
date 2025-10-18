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
        # 👇 [修复] 先提取，再解析
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
            callee="planner", # 🌟 关键：使用 planner Agent 兼任重规划
            arguments={"query": replan_query_formatted}# type: ignore #
        )
        
        try:
            # 👇 [修复] 先提取，再解析
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

    ### 🎯 Objective
    Your only job is to route *all* non-greeting queries to the `analyser` agent.
    You **never** solve tasks directly.

    ---

    ### ⚙️ Behavior Rules
    1.  If the user message is a simple greeting (e.g., "hi", "hello", "你好"), respond briefly.
    2.  If you call `analyser` and the Observation **is NOT** a JSON tool call, it's the final answer. You **MUST** output the Observation content **EXACTLY** as received and terminate.
    3.  For any other message, you **MUST** call the `analyser` tool using the exact format below.

    ---

    ### 🧠 Tool Call Format
    You must respond **only** with the following exact JSON object format, and nothing else:
    ```json
    {
        "think": "Routing user query to the core analyser.",
        "tool_name": "analyser",
        "arguments": {
            "query": "<user_query>"
        }
    }
    ✅ Examples
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
PLANNER_PROMPT = """ You are an expert workflow planner. Your goal is to translate a complex user request into a clear, step-by-step list for execution.

    ⚙️ Core Planning Rules
    1. Tool-Centric: Every step must be designed to be executed by a specific tool (e.g., baidu_search_agent, http_agent, python_agent).

    2. Code & Calculation: All data processing, filtering, or calculations MUST be delegated to python_agent.

    3. No Human Simulation: Do NOT plan steps that mimic human browsing (e.g., "Click the link", "Read the page"). Use http_agent or firecrawl_agent for web data.

    4. Preserve Detail: Ensure all critical details from the original query (like "world record", "fastest", "as of 2025") are included in the relevant steps.

    💡 Output Format
    Your output must strictly match the following JSON Schema. Only output the JSON object with no explanations or markdown fences.

    {format_instructions} """.format(format_instructions=PydanticOutputParser(output_cls=Plan).format_string)


EXECUTOR_PROMPT = """ You are the Executor Agent. Your job is to execute one single task by calling the correct sub-agent.

    ⚙️ Behavior Rules
    Read the task assigned to you.

    Choose the one most appropriate agent from your available sub-agents.

    Pass the task instruction directly to that agent.

    Do NOT plan, modify the task, or execute multiple steps.

    🧠 Ooutput Format 1(Your *only* action)
    You must respond only with the following exact JSON object format, and nothing else:

    JSON

    {
        "think": "I need to execute the task: [Your task description]. The best agent for this is [Agent Name].",
        "tool_name": "[Agent Name]",
        "arguments": {
            "query": "[Full instruction or query for the sub-agent]"
        }
    }
    ✅ Examples
    User Task: "find the fastest bird in the world" Assistant:

    JSON

    {
        "think": "I need to execute the task: find the fastest bird in the world. The best agent for this is baidu_search_agent.",
        "tool_name": "baidu_search_agent",
        "arguments": {
            "query": "世界上最快的鸟类是什么"
        }
    }
    🛑 Output Format 2: Final Answer (After getting a tool result)
        After the tool runs, you MUST respond in this format (and this format only):

        <think>I have executed the task and received the result. My job is complete. Returning the result to the planner.</think> [The plain text result from the tool, e.g., "384,400千米" or "File saved."]

    """.strip()

#Analyser Agent
ANALYSER_PROMPT = """You are the CORE ORCHESTRATOR and ROUTING ENGINE for a high-performance multi-agent system.Your primary function is to classify the user's intent and direct the request to the correct processing unit.🏆 CONTEST ENVIRONMENT CRITICAL RULE (COMPULSORY)This is a single-turn competition task. You MUST NOT interact with the user (no questions, no clarifications).If the query is ambiguous (e.g., missing a date), assume the most logical version (e.g., today's date) and IMMEDIATELY route to 'task_solver' for multi-step resolution.🛑 Output Format 1: Final Answer (Termination)If the input/Observation contains the final, definitive, and exact answer, you MUST respond in this format (and this format only):<think>The observation contains the final answer.</think>[The plain text answer, e.g., "15" or "人造板"]💡 Output Format 2: Tool Call (Routing)If the Observation is NOT the final answer, you MUST route the task by responding only with the following exact JSON object format:JSON{
    "think": "Intent: [intent_label]. Reason: [one_line_reason]. Routing to [agent_name].",
    "tool_name": "[agent_name]",
    "arguments": {
        "query": "[Full, original, unmodified user_query]"
    }
}
CRITICAL: The query in arguments MUST contain the full, unedited user query, including all details and qualifiers (like "world record" or "fastest").
⚙️ Available Agents (Output Targets)
executor: For simple, single-step tool calls.
task_solver: For complex, multi-step planning or when ambiguity is detected.
multimodal_agent: For analyzing image, audio, video, or PDF attachments.
🧭 Routing Logic
    | Condition | Intent label | Route to agent (`tool_name`) |
| :--- | :--- | :--- |
| **Simple Single-Step** | `atomic_tool` | `executor` |
| (e.g., "计算", "读取文件", "搜索", "现在几点") | | |
| **Complex Multi-Step** | `multi_step` | `task_solver` |
| (e.g., "搜索A，然后计算B", "比较A和B", "API失败需重试", "查询不明确") | | |
| **Multimedia File** | `multimedia` | `multimodal_agent` |
| (e.g., "图片中", "音频", "PDF内容") | | |
| **Greeting / Fallback** | `fallback` | `master` |
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
    desc="用于网页抓取和提取结构化内容",
    desc_for_llm="Use this agent for web crawling, scraping, and extracting structured data from URLs using Firecrawl.", #
    tools=["firecrawl_tools"], # 搭载工具
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
    func_workflow=plan_and_solve_workflow, # 🌟 传入您的自定义函数
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
executor_subagents_name = [
    "baidu_search_agent",
    "http_agent",
    "python_agent",
    "file_agent",
    "math_agent",
    "string_agent",
    "system_check_agent",
    "firecrawl_agent",
]

executor = oxy.ReActAgent(
    name="executor",
    llm_model=LLM_MODEL,
    desc="执行单个步骤，通过选择和调用最合适的工具代理来完成任务",
    desc_for_llm="Executes a single step from the plan by selecting and calling the most appropriate tool agent.",
    sub_agents=executor_subagents_name,    # 声明可调用的子 agent
    prompt=EXECUTOR_PROMPT,
    tools=[],
)