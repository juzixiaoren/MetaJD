from oxygent import preset_tools
from oxygent import oxy
import os
from .file_tools import file_tools as file_tools  # 导入我们新建的 file_tools
from .video_tools import video_tools as video_tools
from .baidu_ocr import baidu_ocr_tool as image_tools
from .audio_tools import audio_tools

from tools.get_github_his import github_h_tools
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
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
dashscope_api_key = os.getenv("DASHSCOPE_API_KEY")
if not dashscope_api_key:
    print("⚠️ 警告: 未在环境变量中找到 DASHSCOPE_API_KEY。阿里云百炼搜索工具可能无法认证。")

bailian_web_search_tools = oxy.SSEMCPClient(
    name="bailian_web_search_tools", # 工具的唯一名称
    sse_url="https://dashscope.aliyuncs.com/api/v1/mcps/WebSearch/sse", # 提供的 baseUrl
    headers={
        # 设置认证头，使用 f-string 动态插入密钥
        "Authorization": f"Bearer {dashscope_api_key}" if dashscope_api_key else ""
    },
    # 你可以根据需要添加 description
    description="阿里云百炼提供的联网搜索工具，用于实时互联网信息检索。"
)
webparsec_tools = oxy.SSEMCPClient(
    name="webparsec_tools", # 工具的唯一名称
    sse_url="https://dashscope.aliyuncs.com/api/v1/mcps/WebParser/sse", # 提供的 baseUrl
    headers={
        # 设置认证头，使用 f-string 动态插入密钥
        "Authorization": f"Bearer {dashscope_api_key}" if dashscope_api_key else ""
    },
    # 你可以根据需要添加 description
    description="网页解析工具，用于提取网页内容和结构化信息。"
)
github_tools = oxy.SSEMCPClient(
    name="github_tools", # 工具的唯一名称
    sse_url="https://dashscope.aliyuncs.com/api/v1/mcps/gitHub/sse", # 提供的 baseUrl
    headers={
        # 设置认证头，使用 f-string 动态插入密钥
        "Authorization": f"Bearer {dashscope_api_key}" if dashscope_api_key else ""
    },
    # 你可以根据需要添加 description
    description="GitHub 官方提供的服务，为开发人员和工具提供连接 GitHub 的高级自动化和交互功能。"
)

dashscope_api_key = os.getenv("DASHSCOPE_API_KEY")
if not dashscope_api_key:
    print("⚠️ (stock_tools) 警告: 未在环境变量中找到 DASHSCOPE_API_KEY。股票工具将无法认证。")

stock_tools = oxy.StreamableMCPClient(
    name="stock_tools",
    server_url="https://dashscope.aliyuncs.com/api/v1/mcps/market-cmapi010845/mcp",
    headers={
        "Authorization": f"Bearer {dashscope_api_key}" if dashscope_api_key else ""
    },
    description="用于查询沪深港股 历史行情、股票列表 和大盘指数 的工具。"
)
CHROME_PROFILE_PATH = os.path.join(PROJECT_ROOT, ".chrome_mcp_profile")
chrome_devtools = oxy.StdioMCPClient(
    name="chrome_devtools",
    params={
        "command": "npx",
        "args": [
            "-y",
            "chrome-devtools-mcp@latest",
            # 关键：告诉 MCP 连接到您已打开的浏览器
            "--browser-url=http://127.0.0.1:9222" #
        ]
    },
    timeout=120 
)
all_tools = [
    preset_tools.time_tools,
    preset_tools.math_tools,
    preset_tools.baidu_search_tools,
    preset_tools.python_tools,
    preset_tools.shell_tools,
    preset_tools.string_tools,
    preset_tools.system_tools,
    file_tools,
    firecrawl_tools,
    bailian_web_search_tools,
    webparsec_tools,
    github_tools,
    github_h_tools,
    video_tools,
    image_tools,
    stock_tools,
    audio_tools,
    chrome_devtools,
]

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