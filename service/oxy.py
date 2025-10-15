import asyncio, os
from oxygent import MAS, oxy,Config

## plan_parser = PydanticOutputParser(Plan)  ## 目的解释器
## action_parser = PydanticOutputParser(Action) ## 行动解释器
Config.set_agent_llm_model("qwen")  # 设置默认的 llm 模型
LLM_MODEL = "qwen"  # Or any llm you can call
file_tools = oxy.StdioMCPClient(
    name="文件管理系统",
    params={
        "command": "npx",
        "args": ["-y", "@modelcontextprotocol/server-filesystem", "./data"],
    },
)
## 示例
'''oxy_my_tools = oxy.StdioMCPClient(  
name="my_tools",
    params={
        "command": "uv", 
        "args": ["--directory", "./mcp_servers", "run", "my_tools.py"], //启动一个 MCP 工具服务，它通过运行 uv --directory ./mcp_servers run my_tools.py 启动。
    },//启动后，agent就可以调用该工具的一些方法
) '''
tool_cost_agent = oxy.ReActAgent(
    name="tool_cost_agent",  
    desc="The agent search the cost of path",
    tools=["my_tools/get_cost"],  # You could append tools to local agents.
    llm_model=LLM_MODEL,
)