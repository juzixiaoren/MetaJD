from oxygent import preset_tools
from oxygent import oxy
import os
firecrawl_tools = oxy.StdioMCPClient(
    name="firecrawl_tools",
    params={
        "command":"npx",
        "args":[
        "-y",
        "firecrawl-mcp"
        ],
        "env":{
            "FIRECRAWL_API_KEY":os.getenv("FIRECRAWL_API_KEY")
        }
    },
)

all_tools = [
    preset_tools.time_tools,
    preset_tools.file_tools,
    preset_tools.math_tools,
    preset_tools.baidu_search_tools,
    preset_tools.http_tools,
    preset_tools.python_tools,
    preset_tools.shell_tools,
    preset_tools.string_tools,
    preset_tools.system_tools,
    firecrawl_tools,
]