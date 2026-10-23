import asyncio
import json
import socket
import subprocess
import sys
import time

import pytest
from mcp.client import Client

from ragcompass.mcp_server import Workspace, build_server
from tests.conftest import CORPUS

TOOLS = {"analyze_corpus", "recommend_config", "run_benchmark", "export_config"}


def call(server, name, arguments):
    async def go():
        async with Client(server) as client:
            return await client.call_tool(name, arguments)

    return asyncio.run(go())


@pytest.fixture(scope="module")
def server():
    return build_server(Workspace([CORPUS.parent]))


def test_lists_the_four_tools(server):
    async def go():
        async with Client(server) as client:
            return await client.list_tools()

    tools = asyncio.run(go()).tools
    assert {tool.name for tool in tools} == TOOLS
    assert all(tool.description for tool in tools)


def test_analyze_and_recommend(server):
    result = call(server, "analyze_corpus", {"path": "corpus", "lang": "es"})
    assert not result.is_error
    data = result.structured_content
    assert data["summary"]["files"] == 9
    assert any(r["key"] == "chunking.documents" for r in data["recommendations"])
    assert "filas de datos" in next(r["reason"] for r in data["recommendations"] if r["key"] == "parser.csv")
    config = call(server, "recommend_config", {"path": str(CORPUS)}).structured_content["config"]
    assert config["chunking"]["tables"]["strategy"] == "row"


def test_benchmark_and_export(server):
    bench = call(
        server, "run_benchmark", {"path": "corpus", "queries": 12, "dense": False}
    ).structured_content
    assert bench["bench"]["queries"] == 12
    assert {r["basis"] for r in bench["recommendations"]} == {"rule-based", "measured"}
    snippet = call(server, "export_config", {"path": "corpus", "target": "langchain"}).structured_content
    assert snippet["filename"] == "ragcompass_langchain.py"
    compile(snippet["content"], "snippet", "exec")


def test_paths_outside_the_roots_are_refused(server):
    result = call(server, "analyze_corpus", {"path": "/etc"})
    assert result.is_error
    assert "outside the allowed roots" in result.content[0].text


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def test_streamable_http_transport():
    port = free_port()
    process = subprocess.Popen(
        [
            sys.executable,
            "-m",
            "ragcompass.cli",
            "mcp",
            "--transport",
            "http",
            "--port",
            str(port),
            "--root",
            str(CORPUS.parent),
        ],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    try:
        for _ in range(100):
            with socket.socket() as s:
                if s.connect_ex(("127.0.0.1", port)) == 0:
                    break
            time.sleep(0.1)

        async def go():
            async with Client(f"http://127.0.0.1:{port}/mcp") as client:
                tools = await client.list_tools()
                result = await client.call_tool("recommend_config", {"path": "corpus"})
                return tools, result

        tools, result = asyncio.run(go())
        assert {tool.name for tool in tools.tools} == TOOLS
        assert result.structured_content["config"]["version"] == 1
    finally:
        process.terminate()
        process.wait(timeout=10)


def test_stdio_transport():
    from mcp import StdioServerParameters

    params = StdioServerParameters(
        command=sys.executable, args=["-m", "ragcompass.cli", "mcp", "--root", str(CORPUS.parent)]
    )

    async def go():
        async with Client(params) as client:
            return await client.call_tool("recommend_config", {"path": "corpus"})

    result = asyncio.run(go())
    assert json.dumps(result.structured_content["config"])


def test_missing_path_is_a_clear_error(server):
    result = call(server, "recommend_config", {"path": "corpus/nope"})
    assert result.is_error and "does not exist" in result.content[0].text
