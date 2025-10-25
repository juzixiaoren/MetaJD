from oxygent import preset_tools
from oxygent import oxy
import os
from .file_tools import file_tools as file_tools  # 导入我们新建的 file_tools
os.environ["FIRECRAWL_API_KEY"] = "fc-8bd1d81dc2d24f82b51dc791d8af2859"
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
# 在 tools/pre_tools.py 中加入（或在该文件末尾添加）
try:
    # 导入你实现的 file_tools（来自 tools/file_tools.py）
    from .file_tools import file_tools as custom_file_tools
except Exception as e:
    custom_file_tools = None
    print("Warning: cannot import custom file_tools:", e)

# 如果 all_tools 未定义，这里先保护一下
try:
    all_tools
except NameError:
    all_tools = []

if custom_file_tools is not None:
    # 移除已有 name == "file_tools" 的条目（如果存在）
    all_tools = [t for t in all_tools if getattr(t, "name", None) != "file_tools"]
    # 然后把你的 custom_file_tools 插入（放在末尾或开头都行）
    all_tools.append(custom_file_tools)

# （可选）调试打印
print("DEBUG: all_tools names:", [getattr(t, "name", type(t).__name__) for t in all_tools])

import requests
import os
import json
if __name__ == "__main__":
    os.environ["FIRECRAWL_API_KEY"] = "fc-8bd1d81dc2d24f82b51dc791d8af2859"

    import asyncio
    import os
    from oxygent import oxy

    async def test_firecrawl():
        firecrawl_tools = oxy.StdioMCPClient(
            name="firecrawl_tools",
            params={
                "command": "npx",
                "args": [
                    "-y",
                    "firecrawl-mcp"
                ],
                "env": {
                    #使用正确的api
                    "FIRECRAWL_API_KEY": "fc-8bd1d81dc2d24f82b51dc791d8af2859"
                }
            },
        )

        print("✅ 启动 MCP 客户端 firecrawl_tools ...")
        try:
            # 尝试直接调用一个简单命令，比如获取版本或测试爬取
            result = await firecrawl_tools.call_tool(
                tool_name="firecrawl_scrape",
                arguments={
                    "url": "https://example.com", "formats": ["markdown"], "maxAge": 172800000
                }
            )
            print("📥 返回结果：", result)

        except Exception as e:
            print("🔥 异常捕获：", e)

    asyncio.run(test_firecrawl())
    import requests

API_KEY = "fc-55539d1c00ad4adb94cddd3ba4c0fa13"
URL = "https://api.firecrawl.dev/v1/scrape?url=https://example.com"

headers = {
    "Authorization": f"Bearer {API_KEY}"
}

print("🚀 Sending test request to Firecrawl API...")
try:
    response = requests.get(URL, headers=headers, timeout=15)
    print("✅ Response Status:", response.status_code)
    print("📦 Response Content (truncated):", response.text[:500])
except requests.exceptions.RequestException as e:
    print("🔥 Request failed:", e)