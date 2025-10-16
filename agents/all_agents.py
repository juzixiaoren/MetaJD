# all_agent.py
import asyncio, os
from oxygent import MAS, oxy,Config,preset_tools
from oxygent.schemas.oxy import OxyRequest, OxyResponse, OxyState
import dotenv
from pydantic import BaseModel, Field
from typing import List, Union
from oxygent.utils.llm_pydantic_parser import PydanticOutputParser # 导入解析器
from tools.pre_tools import all_tools
import json
import sys
from typing import Any, List, Optional, Type, Union

GITHUB_PAT_VALUE = "？"

async def plan_and_solve_workflow(oxy_request: OxyRequest) -> OxyResponse:
    """
    手动实现的规划-执行-反思工作流。
    """
    original_query = oxy_request.get_query()
    max_replan_rounds = 5 # 限制循环次数
    
    # 步骤 1: 初始规划 (调用 planner)
    # 使用 format 格式化查询，要求 planner 返回 Plan Pydantic JSON
    planner_query = plan_parser.format(original_query)
    planner_response = await oxy_request.call(
        callee="planner", 
        arguments={"query": planner_query}
    )
    
    try:
        plan_data = plan_parser.parse(planner_response.output)
        plan_steps = plan_data.steps
    except Exception as e:
        # 如果规划失败，直接返回错误
        return OxyResponse(output=f"规划 Agent 返回格式错误或规划失败: {e}")
        
    past_steps = ""
    
    # 步骤 2: 循环执行与重规划
    for current_round in range(max_replan_rounds):
        if not plan_steps:
            # 计划已执行完，进入最终总结阶段 (跳到步骤 3)
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
            action_data = action_parser.parse(replanner_response.output)
        except Exception as e:
            return OxyResponse(output=f"重规划 Agent 返回格式错误: {e}")

        # 2.4 决策：响应或继续规划
        if hasattr(action_data.action, "response"):
            # 最终答案
            return OxyResponse(output=action_data.action.response)
        else:
            # 新计划
            plan_steps = action_data.action.steps
            
    # 步骤 3: 总结 (如果循环提前结束但没有返回答案)
    # 使用 LLM 总结结果
    summary_query = f"The task was: {original_query}. Final execution history:\n{past_steps}. Please provide the final, exact answer."
    summary_response = await oxy_request.call(
        callee=oxy_request.llm_model, # 使用默认 LLM 进行总结
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

LLM_MODEL = "qwen"
VLM_MODEL = "qwen3-vl-plus"

# ----------------- Agent Prompt ----------------------
MASTER_PROMPT="""
    You are the master coordinator agent for the OxyGent multi-agent system.

    ### 🎯 Objective
    Efficiently complete competition tasks (query-answer type) by delegating work to sub-agents.
    You **never** solve tasks directly.  
    Your only job is to route queries to `analyser`.

    ---

    ### ⚙️ Behavior Rules
    1. If the user message is a simple greeting (e.g., "hi", "hello", "你好"), respond briefly.

    2. If you call a sub-agent and the **Observation is NOT a JSON tool call**, it means the sub-agent has produced the final answer. In this case, you **MUST output the Observation content EXACTLY as received and terminate.** Do NOT add any preamble, conclusion, or modify the text.

    3. If the Observation IS a JSON tool call, you MUST process that tool call.

    4. For any other message not covered above, you MUST call the tool `analyser` with the full user query.
    
    5. Do NOT wrap JSON in ``` or markdown.
    6. Return **only** the JSON tool call — no explanations, no reasoning text.

    ---

    ### 🧠 Tool Call Format
    Exactly this JSON:
    {"tool_name": "analyser", "arguments": {"query": "<user_query>"}}

    ---

    ### ✅ Examples
    User: hi  
    Assistant: Hello!

    User: 京东金融提供了哪些服务？  
    Assistant:  
    {"tool_name": "analyser", "arguments": {"query": "京东金融提供了哪些服务？"}}

    User: 帮我查下京东云的解决方案  
    Assistant:  
    {"tool_name": "analyser", "arguments": {"query": "帮我查下京东云的解决方案"}}

    ---

    Remember:
    - You are a **router**, not a solver.
    - If unsure, **always** call `analyser`.
    """.strip()

# Plan Agent
PLANNER_PROMPT = """
You are a top-tier **Automated Workflow Engineer** and **Process Generator** within a multi-agent execution system.

Your singular goal is to translate complex user requests into the most **efficient, tool-executable, and error-resistant** sequence of steps.

***
### ⚙️ CRITICAL PLANNING CONSTRAINTS (Automation & Tool-First Mandate)
1.  **MANDATORY TOOL CHAINING:** Every executable step **MUST** be designed as a direct input for another specialized Agent/Tool (e.g., baidu_search_agent, http_agent, python_agent). Never plan a step without an explicit tool target.
2. **API/DIRECT ACCESS PREFERENCE:** When calling the GitHub API (e.g., /commits, /repos):
    * The planning step **MUST** specify to use the **Authorization header** to bypass rate limits.
    * The Authorization header value MUST be 'token {GITHUB_PAT_VALUE}' (replace {GITHUB_PAT_VALUE} with the actual token value).
3.  **STRICTLY PROHIBITED BEHAVIOR:** **ABSOLUTELY AVOID** planning steps that mimic human browsing or require visual inspection. This includes: 'Navigate to X', 'Click Y', 'Check Tab Z', 'Read the page for the answer'.
4.  **CODE & CALCULATION:** All data processing, filtering, counting, or complex calculations (after data acquisition) **MUST** be delegated to the **python_agent**.

***


Your task is to receive a complex user request and break it down into a clear, organized, step-by-step execution list.
These steps should be specific enough so that the subsequent execution Agent can directly use them to call tools.

**Core Rules:**
1.  Think through all the logical steps required to complete the task.
2.  Ignore the steps that you have already completed (if any).
3.  Your output must strictly match the following JSON Schema.
4.  **Only output the JSON object** with no explanations, markdown fences, or extra text.

{format_instructions}
""".format(format_instructions=PydanticOutputParser(output_cls=Plan).format_string)

# Executor Agent
EXECUTOR_PROMPT = """
You are a task execution Agent. Your task is to execute the **current single step** provided by the previous Agent, selecting the most appropriate tool or sub-agent to carry out the step.

**Input format:**
- The input contains a step to be executed, along with historical execution results for context.
- You must **only execute the current step**.

---
### ⚙️ Core Rules
1. Decide which underlying tool Agent (e.g., `python_agent`, `baidu_search_agent`) to call.
2. You MUST use the ReAct paradigm, outputting **Thought** before the Tool Call.
3. If the task is completed, output the answer directly (pure text, no JSON).

---
### 💡 Tool Call Format (CRITICAL)
### 💡 Tool Call Format (CRITICAL)
If you decide to call a tool, your output MUST be a JSON object with the exact keys: "tool_name" and "arguments". 

Example API Call using Authorization Header (MANDATORY for GitHub):
{"tool_name": "http_agent", "arguments": {
  "url": "https://api.github.com/repos/...", 
  "headers": {"Authorization": "token %s"} 
}} 
You MUST replace %s with the actual GitHub PAT value when executing a GitHub API call.

Example Tool Call (JSON ONLY, NO MARKDOWN):
{"tool_name": "baidu_search_agent", "arguments": {"query": "Dify GitHub 仓库 URL"}} 
                                    ^^^^^^^^^^
---
"""


#Analyser Agent
ANALYSER_PROMPT = """
You are the **task analyser, router, and result reviewer** in a multi-agent system.

***
### CONTEST ENVIRONMENT CRITICAL RULE (COMPULSORY)
This is a single-turn competition task. You **MUST NOT** interact with the user by asking questions, seeking clarification, or stating that information is unavailable. 
If the current Observation is insufficient or raises ambiguity (like time or version type):
1.  **Assume the most logical version** (e.g., current date, file commit history for 'version').
2.  **IMMEDIATELY route to 'task_solver'** for multi-step resolution.
3.  NEVER return a question or a clarification to the 'master' agent.
***
Your primary goal is to manage the flow of execution:
1. Determine the best agent for the initial query.
2. After a tool returns an Observation, **evaluate the Observation to see if the user's query is answered.**

---
### Termination Rule: When to STOP and Return
**Crucially, if the input/Observation contains the final, definitive, and exact answer to the user's ORIGINAL query, you MUST output the answer as pure text and STOP.** (This is the *only* time you return non-JSON.)
**ONLY the core answer text** as plain text and STOP the tool-calling process.
**Example:**
If the question is "Numpy的random.rand方法是生成符合什么分布的随机数组？" and the answer is "均匀分布", you must output:
均匀分布 
Do NOT include any prefixes like "是的, 答案是" or suffixes like "在区间 [0, 1) 内".
---
### Result Evaluation and Re-routing

If the Observation is NOT the final answer, you must decide the next step:

| Condition | Next Action (Output) |
| :--- | :--- |
| **Answer FOUND** | Output the plain text answer (Termination Rule). |
| **Search Info INSUFFICIENT** | **Route to task_solver** with a query that prompts **re-planning** or **refining the search strategy** (e.g., "The previous search failed. Re-plan to search for X instead of Y"). |
| **Query needs Tool/Agent** | Route to the relevant specialized agent (See 'Available Agents' below). |

---
### Output format (MUST be valid JSON for Routing)

If routing is needed, your decision must be expressed as a **single JSON object**, formatted exactly as below:
{"tool_name": "<agent_name>", "arguments": {"query": "<user_query/next_step_instruction>", "meta": {"intent": "<intent_label>", "reason": "<one_line_reason>"}}}

---

### Intent labels and routing rules
Intent labels and routing rules

| Intent label | Route to agent | Typical trigger words or context |
|---------------|----------------|----------------------------------|
| **file_ops** | file_agent | “读取文件”, “write file”, “data.txt”, “save” |
| **math** | math_agent | “计算”, “多少”, equations, numbers |
| **http_fetch** | http_agent |“访问 URL”, “获取网页”, “API 调用”, “发送数据”, “提交表单”, “POST 请求”, “下载 JSON”, “GET”, “POST”, “fetch” |
| **web_search** | baidu_search_agent | “搜索”, “百度”, “查找…资料” |
| **code_exec** | python_agent / shell_agent | “运行代码”, “执行脚本”, “python xxx.py”, “bash” |
| **nlp_text** | string_agent | “提取URL”, “找出邮箱”|
| **sys_check** | system_check_agent | “系统信息”, “CPU占用”, “内存使用” |
| **time_query** | time_agent | “现在几点”, “转换时区” |
| **fallback** | master | greetings (“hi”, “你好”), small talk |
| **multi_step** | task_solver | multi-step, complex problem, need planning/reflection | 
| **multimedia** | multimodal_agent | “图片中”, “音频”, “文件内容”, “视频”, “PDF” |
---

### Output rules
1. If routing is required, always produce **ONE valid JSON object** only.
2. **If returning the final answer, output ONLY the plain text answer.**
3. **Never** include markdown, explanations, or code fences in the final output.
4. `intent` is one of the labels above.
5. `reason` is a short one-line justification (≤ 15 words).
6. If unsure which tool fits best → choose `fallback` (handled by master).


---
""".strip()

# ----------------- Agent Configuration ----------------------
# preset tools and agents from oxygent
time_agent = oxy.ReActAgent(
    name="time_agent",
    desc="""A timezone-aware time utility toolset.
            It can:
            1. Retrieve the current local time in a specific timezone.
            2. Convert time between different IANA timezones.
            Useful for scheduling, time synchronization, and timezone conversions.""",
    tools=["time_tools"],
    llm_model=LLM_MODEL,
)

file_agent = oxy.ReActAgent(
    name="file_agent",
    desc="Use this agent for file system operations: "
         "reading, writing, deleting, renaming, or checking if files exist. "
         "Cannot list folders or execute code.",
    tools=["file_tools"],
    llm_model=LLM_MODEL,
)

math_agent = oxy.ReActAgent(
    name="math_agent", 
    desc="Use this agent to perform precise or safe mathematical operations, "
         "like computing pi, doing element-wise list math, or evaluating math expressions.", 
    tools=["math_tools"],
    llm_model=LLM_MODEL,
)

baidu_search_agent = oxy.ReActAgent(
    name="baidu_search_agent",
    desc="Use this agent to search information on the web through Baidu API "
         "and retrieve online content or answers.",
    tools=["baidu_search_tools"],
    llm_model=LLM_MODEL,
)

http_agent = oxy.ReActAgent(
    name="http_agent",
    desc="""This agent is designed to execute **HTTP network requests**, 
    primarily using **GET** and **POST** methods to interact with external APIs or web resources. 
    It can be used for **fetching data**, **querying information**, **downloading web content**, or **submitting JSON-formatted data** to a server. The request result is returned in a JSON format that includes the status code and content.
    **Do not attempt to use this agent for code execution or file system operations.**""",
    tools=["http_tools"],
    llm_model=LLM_MODEL,
)

python_agent = oxy.ReActAgent(
    name="python_agent",
    desc="Use this agent to safely execute short Python code snippets or evaluate expressions. "
         "It does not run external .py files or system commands.",
    tools=["python_tools"],
    llm_model=LLM_MODEL,
)

shell_agent = oxy.ReActAgent(
    name="shell_agent",
    desc="Use this agent to execute full shell commands in the system environment, "
         "such as ls, cat, python xxx.py, or bash commands. "
         "Best for interacting with the OS or running scripts.",
    tools=["shell_tools"],
    llm_model=LLM_MODEL,
)

string_agent = oxy.ReActAgent(
    name="string_agent",
    desc="""A set of utilities for text analysis and string extraction tasks.
            This tool can:
            1. Extract all valid email addresses from any given text.
            2. Extract all valid URLs (http/https) from a text.
            3. Validate whether a given string is a properly formatted email address.""",
    tools=["string_tools"],
    llm_model=LLM_MODEL,
)

system_check_agent = oxy.ReActAgent(
    name="system_check_agent",
    desc="""A toolset for system inspection and resource monitoring.
            It can:
            1. Retrieve detailed system information, including OS, architecture, processor, and Python version.
            2. Check real-time resource usage such as CPU load, memory usage, and disk utilization.
            Useful for environment diagnostics, runtime monitoring, and ensuring resource availability before executing heavy tasks.""",
    tools=["system_tools"],
    llm_model=LLM_MODEL,
)



# Plan and Action Parser
plan_parser = PydanticOutputParser(output_cls=Plan)
action_parser = PydanticOutputParser(output_cls=Action)

# Agents
planner = oxy.ChatAgent(
    name="planner",
    llm_model=LLM_MODEL,
    desc="A dedicated agent for generating multi-step, sequential plans in JSON format for complex tasks.",
    prompt=PLANNER_PROMPT,
)

executor_sub_agents = [
    "baidu_search_agent", "http_agent", "file_agent", "python_agent", 
    "shell_agent", "math_agent", "string_agent", "time_agent", "multimodal_agent"
]

executor = oxy.ReActAgent(
    name="executor",
    llm_model=LLM_MODEL,
    desc="Executes a single step from the plan by selecting and calling the most appropriate tool agent.",
    sub_agents=executor_sub_agents,
    prompt=EXECUTOR_PROMPT,
)



analyser = oxy.ReActAgent(
    name="analyser",
    desc="Route queries to the right agent based on intent (web, file, image, audio, code, math, sql, etc.). Outputs a single JSON tool call.",
    prompt=ANALYSER_PROMPT,
    llm_model=LLM_MODEL,
    # give analyser access to general LLM but not necessarily to the low-level tools.
    # It only needs to output routing JSON; actual execution will be by the chosen agent.
    sub_agents=[
    "baidu_search_agent",
    "http_agent",
    "file_agent",
    "system_check_agent",
    "python_agent",
    "shell_agent",
    "math_agent",
    "task_solver",
    "multimodal_agent",
    "string_agent"
], 
    history_limit=0, #不受历史记录影响
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

async def plan_and_solve_workflow(oxy_request: OxyRequest) -> OxyResponse:
    """
    手动实现的规划-执行-反思工作流。
    """
    original_query = oxy_request.get_query()
    max_replan_rounds = 5 # 限制循环次数
    
    # 步骤 1: 初始规划 (调用 planner)
    # 使用 format 格式化查询，要求 planner 返回 Plan Pydantic JSON
    planner_query = plan_parser.format(original_query)
    planner_response = await oxy_request.call(
        callee="planner", 
        arguments={"query": planner_query}
    )
    
    try:
        plan_data = plan_parser.parse(planner_response.output)
        plan_steps = plan_data.steps
    except Exception as e:
        # 如果规划失败，直接返回错误
        return OxyResponse(output=f"规划 Agent 返回格式错误或规划失败: {e}")
        
    past_steps = ""
    
    # 步骤 2: 循环执行与重规划
    for current_round in range(max_replan_rounds):
        if not plan_steps:
            # 计划已执行完，进入最终总结阶段 (跳到步骤 3)
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
            action_data = action_parser.parse(replanner_response.output)
        except Exception as e:
            return OxyResponse(output=f"重规划 Agent 返回格式错误: {e}")

        # 2.4 决策：响应或继续规划
        if hasattr(action_data.action, "response"):
            # 最终答案
            return OxyResponse(output=action_data.action.response)
        else:
            # 新计划
            plan_steps = action_data.action.steps
            
    # 步骤 3: 总结 (如果循环提前结束但没有返回答案)
    # 使用 LLM 总结结果
    summary_query = f"The task was: {original_query}. Final execution history:\n{past_steps}. Please provide the final, exact answer."
    summary_response = await oxy_request.call(
        callee=oxy_request.llm_model, # 使用默认 LLM 进行总结
        arguments={"query": summary_query}
    )
    
    return summary_response
# Plan and Solve Agent
task_solver = oxy.WorkflowAgent(
    name="task_solver",
    llm_model=LLM_MODEL,
    desc="Solve complex, multi-step tasks using a custom Plan-Execute-Reflect workflow.",
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