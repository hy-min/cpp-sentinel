"""cpp_sentinel MCP server:审查能力暴露成 MCP 工具,任意 agent 可直调。

用法(开发自测,会挂在 stdio 等客户端):
    python -m cpp_sentinel.mcp_server
"""
import os

# ── R1 铁律:任何 LLM 库 import 之前清代理 ──
for v in ["HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY",
          "http_proxy", "https_proxy", "all_proxy"]:
    os.environ.pop(v, None)

from mcp.server import MCPServer           # mcp 2.x 高层 API(1.x 的 fastmcp 已改名)

from cpp_sentinel.cli import run
from cpp_sentinel.report import make_report

mcp = MCPServer("cpp-sentinel")            # ① 起一个 server,名字唯一


@mcp.tool()                                # ② 装饰器:下边函数变成"工具"
def cpp_review(repo: str, limit: int = 5) -> str:
    """审查一个 C++ 仓库:先 clang-tidy 扫告警,再 LLM 逐条去噪,返回摘要。

    参数:
        repo: C++ 仓库路径(需已生成 build/compile_commands.json)
        limit: 最多让 LLM 判定多少条(先小后大,省 token)
    返回: 四态摘要文本;失败项单独计数。
    """
    try:
        results = run(repo, limit)                  # ③ 复用课6 管线(第三件西装!)
    except SystemExit as e:                         # ④ 配置错误(SystemExit)→ 友好消息
        return f"❌ {e}"
    report = make_report(results)
    s = report["summary"]
    return (f"共 {report['total']} 条告警: 真问题 {s['real']} / 疑似 {s['suspicious']} / "
            f"忽略 {s['ignore']} / 失败 {s['failed']}")


if __name__ == "__main__":
    mcp.run()                               # ⑤ stdio 模式:标准输入/输出跟客户端说话
