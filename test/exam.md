### 本文档用于辅助理解项目各组成部分如何使用以及相关参数解释

```python

# %%

# pyright: reportGeneralTypeIssues=false

# pyright: basic

```

```python

import asyncio, os

from oxygent import MAS, oxy, Config

Config.set_agent_llm_model("qwen")  # 设置默认的 llm 模型

LLM_MODEL ="qwen"  # Or any llm you can call

```

#### 工具定义

```python

file_tools = oxy.StdioMCPClient(

    name="文件管理系统",

    params={

        "command": "npx",

        "args": ["-y", "@modelcontextprotocol/server-filesystem", "./data"],  # 使用 npx 启动 MCP 文件系统服务，数据目录为 ./data

    },

)


# 示例

oxy_my_tools = oxy.StdioMCPClient(

    name="my_tools",

    params={

        "command": "uv",

        "args": ["--directory", "./mcp_servers", "run", "my_tools.py"],  # 启动一个 MCP 工具服务，它通过运行 uv --directory ./mcp_servers run my_tools.py 启动。

    },

)  # 启动后，agent 就可以调用该工具的一些方法

```

#### agent定义

```python

# 定义一个具有工具调用能力的 ReAct（Reason + Act）智能体，

# 用于根据问题推理并调用工具获取信息（如路径成本）。

tool_cost_agent = oxy.ReActAgent(

    name="tool_cost_agent",

    # 智能体的名称，用于在多智能体系统中识别和调用。

    desc="The agent search the cost of path",

    # 描述该智能体的功能，帮助其他智能体或系统理解其用途。

    # 此处说明它用于查询路径的成本。

    tools=["my_tools/get_cost"],

    # 指定该智能体可以使用的工具列表。

    # "my_tools/get_cost" 是一个自定义工具（通常在 oxy 工具注册系统中定义），

    # 用于根据输入（如起点、终点）返回路径成本。

    # 注意：工具名需与 oxy 中注册的工具名称一致。

    llm_model=LLM_MODEL,

    # 指定该智能体使用的底层大语言模型（如 "gpt-4", "claude-3", 或本地模型）。

    # LLM_MODEL 应已在代码其他地方定义，例如 LLM_MODEL = "gpt-4o"

)


# 定义一个专门用于生成计划（plan）的聊天智能体。

planner = oxy.ChatAgent(

    name="planner",

    # 智能体名称。

    llm_model=LLM_MODEL,

    # 使用的 LLM 模型。

    prompt=(

        "You are a planning agent.  "

        "Output **only** a JSON object that matches this schema:\n "

        '{"steps": ["step 1", "step 2", ...]}\n'

    ),

    # 系统提示（system prompt），严格约束输出格式。

    # 要求该智能体只输出符合指定 JSON Schema 的对象，

    # 例如：{"steps": ["查询起点到终点的路径", "获取该路径的成本", "输出总成本"]}

    # 这种强格式约束便于后续程序解析。

)


# 定义一个“计划-执行”型智能体（Plan-and-Solve Agent），

# 它会先调用 planner 生成计划，再调用 executor 执行计划中的每一步。

analyser = oxy.PlanAndSolveAgent(

    name="analyser",

    # 智能体名称。

    llm_model=LLM_MODEL,

    # 使用的 LLM 模型（虽然 planner 和 executor 可能已有自己的模型，但此处可能用于协调或重试逻辑）。

    planner_agent_name=planner.name,

    # 指定用于生成计划的 planner 智能体名称（即上面定义的 "planner"）。

    # PlanAndSolveAgent 会在内部调用该 planner 来获取步骤列表。

    executor_agent_name=executor.name,

    # 指定用于执行计划中每一步的 executor 智能体名称。

    # 注意：代码中未定义 executor，但应已存在，例如一个能调用 tool_cost_agent 的执行器。

    # executor 通常负责将 plan 中的自然语言步骤转化为具体动作（如调用工具）。

    pydantic_parser_planner=plan_parser,

    # 用于解析 planner 输出的 Pydantic 模型。

    # plan_parser 应是一个继承自 pydantic.BaseModel 的类，例如：

    #   class Plan(BaseModel):

    #       steps: List[str]

    # 这确保 planner 的输出被严格验证并转换为结构化对象。

    pydantic_parser_replanner=action_parser,

    # 用于在启用重规划（replanning）时解析新动作的 Pydantic 模型。

    # 即使当前未启用重规划，也可能需要提供（取决于框架实现）。

    enable_replanner=False,

    # 是否启用“重规划”机制。

    # 若为 True，当执行某步失败时，会调用 replanner 生成修正后的步骤。

    # 此处设为 False，表示执行失败时不会自动重规划，可能直接报错或停止。

)

```

```python

from oxygent import preset_tools

print(dir(preset_tools))

```

预设的工具：'FunctionHub', '__all__', '__builtins__', '__cached__', '__doc__', '__file__', '__loader__', '__name__', '__package__', '__path__', '__spec__', 'attr_name', 'attr_value', 'baidu_search_tools', 'error_msg', 'file_tools', 'function_hub_instances', 'http_tools', 'importlib', 'math_tools', 'missing_package', 'module', 'module_name', 'module_path', 'os', 'package_dir', 'python_tools', 'shell_tools', 'string_tools', 'system_tools', 'time_tools', 'tool_modules'

#### 说明

- baidu_search_tools 可用于通过百度来搜索获取相关内容
- file_tools 支持对文件进行建删读写操作，但是必须指定文件路径，他无法列出某文件夹下面的文件
- http_tools 可以获取网页的元素，也可以用 http 发送 post 或者 get 请求
- math_tools 用于求解数学问题
- python_tools 用于执行 python 代码（无法直接读取和保存），返回某个具体变量的值，如果没设置则返回执行状态
- shell_tools 执行一条 shell 命令
- sql_tools 是一个用于安全访问数据库的工具集，支持列出表名、查看表结构、执行 SQL 查询，基于 SQLAlchemy 连接，通过环境变量配置数据库连接（暂时没有）
- system_tools 是一个用于 系统监控与环境检测 的工具集（FunctionHub），非常实用，主要帮助 agent 了解当前运行环境的系统信息与资源状态。
- train_ticket_tools 是一个 火车票查询与车站信息工具集，基于 12306 官方数据源，能帮助智能体完成从自然语言提问 → 城市解析 → 车票查询的一整套操作（暂时也没有？）

```python

planner_agent = oxy.ReActAgent(

    name="planner_agent",

    desc="For complex, multi-step tasks. Decomposes the task into a sequence of steps and calls other agents to execute them.",

    llm_model=LLM_MODEL,

    prompt="""

    You are a planner. Your job is to break down a complex user query into a series of simple, executable steps.

    Each step must be a call to one of the available tools.

    Analyze the user's query and output a JSON array of tool calls.

  

    Available agents/tools: baidu_search_agent, file_agent, shell_agent, python_agent, math_agent, http_agent ...

  

    Example Query: "搜索珠穆朗玛峰的高度，并将其写入 height.txt"

    Output Plan:

    [

        {"tool_name": "baidu_search_agent", "arguments": {"query": "珠穆朗玛峰的高度"}},

        {"tool_name": "file_agent", "arguments": {"tool_name": "write", "args": {"path": "height.txt", "content": "<output_of_step_1>"}}}

    ]

    """.strip(),

    # Planner 需要能调用所有执行类的 agent

    sub_agents=[

        "baidu_search_agent",

        "http_agent",

        "file_agent",

        "system_check_agent",

        "python_agent",

        "shell_agent",

        "math_agent",

        "string_agent"

    ]

)

```

```bash

# 存代码（设置代理）

sethttp_proxy=http://127.0.0.1:10809

setHTTP_PROXY=http://127.0.0.1:10809

sethttps_proxy=http://127.0.0.1:10809

setHTTPS_PROXY=http://127.0.0.1:10809

```
