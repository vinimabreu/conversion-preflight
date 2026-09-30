"""Talk to the Sanity Context MCP endpoint over plain HTTP, no model involved.

    python tools/mcp_probe.py            # server info and tool list
    python tools/mcp_probe.py outline    # the knowledge base outline (initial_context)
"""
import json
import sys
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from preflight.common import load_env  # noqa: E402

ENV = load_env(Path(__file__).resolve().parent.parent / ".env")
if not {"SANITY_CONTEXT_MCP_URL", "SANITY_ORGANIZATION_TOKEN"} <= ENV.keys():
    sys.exit("set SANITY_CONTEXT_MCP_URL and SANITY_ORGANIZATION_TOKEN in .env first")
URL, TOKEN = ENV["SANITY_CONTEXT_MCP_URL"], ENV["SANITY_ORGANIZATION_TOKEN"]
_session: dict[str, str] = {}


def rpc(method: str, params: dict | None = None, id_: int | None = 1):
    body = {"jsonrpc": "2.0", "method": method}
    if id_ is not None:
        body["id"] = id_
    if params is not None:
        body["params"] = params
    headers = {"Authorization": f"Bearer {TOKEN}", "Content-Type": "application/json",
               "Accept": "application/json, text/event-stream"}
    if "sid" in _session:
        headers["Mcp-Session-Id"] = _session["sid"]
    req = urllib.request.Request(URL, data=json.dumps(body).encode(), headers=headers, method="POST")
    with urllib.request.urlopen(req, timeout=60) as r:
        if r.headers.get("Mcp-Session-Id"):
            _session["sid"] = r.headers["Mcp-Session-Id"]
        raw = r.read().decode()
    if id_ is None:
        return None
    if raw.lstrip().startswith("{"):
        return json.loads(raw)
    for line in raw.splitlines():
        if line.startswith("data:"):
            return json.loads(line[5:])
    return raw


def connect():
    init = rpc("initialize", {"protocolVersion": "2025-06-18", "capabilities": {},
                              "clientInfo": {"name": "preflight-probe", "version": "0.1"}})
    rpc("notifications/initialized", id_=None)
    return init["result"]


def call(name: str, arguments: dict) -> str:
    out = rpc("tools/call", {"name": name, "arguments": arguments}, 9)
    return "".join(c.get("text", "") for c in out["result"]["content"])


if __name__ == "__main__":
    info = connect()
    print("server:", info.get("serverInfo"))
    print("tools:", [t["name"] for t in rpc("tools/list", {}, 2)["result"]["tools"]])
    if len(sys.argv) > 1 and sys.argv[1] == "outline":
        print(call("initial_context", {}))
