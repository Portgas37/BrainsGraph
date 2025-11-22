import asyncio
import json
import sys
import threading
import logging
import os
import re
import argparse
from typing import List, Set

import uvicorn
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse
from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp.types import Tool, TextContent, ImageContent, EmbeddedResource

# Force logging to stderr to keep stdout clean for MCP protocol
logging.basicConfig(stream=sys.stderr, level=logging.INFO)
logger = logging.getLogger("BrainsGraph")

# --- 1. SCANNER ---
def scan_repository(root_path: str):
    nodes = []
    edges = []
    file_map = {} 

    if not os.path.exists(root_path):
        logger.error(f"PATH NOT FOUND: {root_path}")
        return [], []

    logger.info(f"Scanning: {root_path}")
    
    for root, dirs, files in os.walk(root_path):
        dirs[:] = [d for d in dirs if d not in ["node_modules", ".git", "venv", "__pycache__", "build", "dist", ".idea"]]
        for file in files:
            if file.endswith(('.ts', '.tsx', '.js', '.jsx', '.py', '.java', '.kt', '.go', '.rs', '.cpp')):
                rel_path = os.path.relpath(os.path.join(root, file), root_path).replace("\\", "/")
                
                node_type = "component" 
                lower = rel_path.lower()
                if "service" in lower: node_type = "service"
                elif "util" in lower or "helper" in lower: node_type = "utility"
                elif "config" in lower: node_type = "config"
                elif "app" in lower or "main" in lower or "controller" in lower: node_type = "core"
                
                nodes.append({
                    "id": rel_path,
                    "label": file,
                    "type": node_type
                })
                file_map[file] = rel_path

    # Regex for imports
    import_pattern = re.compile(r'(?:import|from|include)\s+["\']?([@\w\.\/-]+)["\']?')
    for node in nodes:
        try:
            with open(os.path.join(root_path, node["id"]), 'r', encoding='utf-8', errors='ignore') as f:
                matches = import_pattern.findall(f.read())
                for match in matches:
                    clean = os.path.basename(match).split('.')[0]
                    for target_file, target_id in file_map.items():
                        if target_file.startswith(clean) and target_id != node["id"]:
                            edges.append({"source": node["id"], "target": target_id})
                            break
        except: pass

    return nodes, edges

# --- 2. STATE ---
class GraphState:
    def __init__(self):
        self.nodes = []
        self.edges = []
        self.highlighted_ids: Set[str] = set()
        self.active_connections: List[WebSocket] = []
        self.loop = None

    def update_highlights(self, ids: List[str]):
        self.highlighted_ids = set(ids)
        if self.loop and self.loop.is_running():
            asyncio.run_coroutine_threadsafe(self.broadcast(), self.loop)

    async def broadcast(self):
        msg = { "type": "UPDATE", "highlighted": list(self.highlighted_ids) }
        for ws in self.active_connections:
            try: await ws.send_json(msg)
            except: pass

state = GraphState()

# --- 3. WEB SERVER ---
app = FastAPI()
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])

@app.on_event("startup")
async def startup_event():
    state.loop = asyncio.get_running_loop()

@app.get("/")
async def get():
    # Serve index.html from same folder
    try:
        with open(os.path.join(os.path.dirname(__file__), "index.html"), "r") as f:
            return HTMLResponse(content=f.read())
    except FileNotFoundError:
        return HTMLResponse(status_code=404, content="index.html not found in backend folder")

@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    await websocket.accept()
    state.active_connections.append(websocket)
    try:
        await websocket.send_json({
            "type": "INIT", 
            "nodes": state.nodes, 
            "edges": state.edges,
            "highlighted": list(state.highlighted_ids)
        })
        while True: await websocket.receive_text()
    except WebSocketDisconnect:
        state.active_connections.remove(websocket)

# --- 4. MCP SERVER ---
mcp = Server("BrainsGraph-MCP")

@mcp.list_tools()
async def list_tools() -> list[Tool]:
    return [
        Tool(
            name="highlight_architecture",
            description="Highlight files in the graph. Use this when explaining code structure.",
            inputSchema={
                "type": "object",
                "properties": {
                    "filenames": {
                        "type": "array", "items": {"type": "string"},
                        "description": "List of filenames to highlight (e.g. ['AuthService.ts'])"
                    }
                },
                "required": ["filenames"]
            }
        )
    ]

@mcp.call_tool()
async def call_tool(name: str, arguments: dict) -> list[TextContent | ImageContent | EmbeddedResource]:
    if name == "highlight_architecture":
        targets = arguments.get("filenames", [])
        found = []
        for target in targets:
            for node in state.nodes:
                if target.lower() in node["id"].lower() or target.lower() in node["label"].lower():
                    found.append(node["id"])
        
        state.update_highlights(found)
        return [TextContent(type="text", text=f"Highlighted {len(found)} files.")]
    
    raise ValueError(f"Tool {name} not found")

# --- 5. RUNNER ---
if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("path", help="Absolute path to the repo to analyze")
    args = parser.parse_args()

    state.nodes, state.edges = scan_repository(args.path)

    t = threading.Thread(target=lambda: uvicorn.run(app, host="0.0.0.0", port=8000, log_config=None, access_log=False), daemon=True)
    t.start()
    
    asyncio.run(asyncio.run(stdio_server())(mcp.run))