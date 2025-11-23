#!/usr/bin/env python3
"""
MCP Server for managing code graph structure.
Provides tools to create and manage nodes and edges representing code structure.
"""

import json
import os
import shutil
from pathlib import Path
from typing import Any

from fastmcp import FastMCP

# Initialize FastMCP server
mcp = FastMCP("Code Graph Server")

# Configuration
DEFAULT_GRAPH_FILE = "code_graph.json"
GRAPH_FILE_PATH = os.getenv("GRAPH_FILE_PATH", str(Path(__file__).parent / DEFAULT_GRAPH_FILE))


def load_graph() -> dict[str, Any]:
    """Load the graph from JSON file, create if doesn't exist."""
    if not os.path.exists(GRAPH_FILE_PATH):
        # Create empty graph
        graph = {"nodes": [], "edges": [], "highlightQuestions": {}}
        save_graph(graph)
        return graph

    with open(GRAPH_FILE_PATH, "r") as f:
        graph = json.load(f)
        # Ensure highlightQuestions exists
        if "highlightQuestions" not in graph:
            graph["highlightQuestions"] = {}
        return graph


def save_graph(graph: dict[str, Any]) -> None:
    """Save the graph to JSON file."""
    with open(GRAPH_FILE_PATH, "w") as f:
        json.dump(graph, f, indent=2)


def get_next_edge_id(graph: dict[str, Any]) -> str:
    """Generate next edge ID."""
    if not graph["edges"]:
        return "edge_0"

    # Extract numeric part from existing edge IDs
    max_id = 0
    for edge in graph["edges"]:
        if edge["id"].startswith("edge_"):
            try:
                num = int(edge["id"].split("_")[1])
                max_id = max(max_id, num)
            except (IndexError, ValueError):
                continue

    return f"edge_{max_id + 1}"


@mcp.tool()
def init_graph(path: str) -> str:
    """
    Initialize a new code graph at the specified path.
    Creates a .brainsGraph directory with code_graph.json and graph-viewer.html.

    Args:
        path: Root directory path of the codebase where .brainsGraph folder should be created

    Returns:
        str: Status message indicating success and the path where graph was initialized
    """
    global GRAPH_FILE_PATH

    # Convert to absolute path
    abs_root = os.path.abspath(path)

    # Create .brainsGraph directory
    brains_graph_dir = os.path.join(abs_root, ".brainsGraph")
    os.makedirs(brains_graph_dir, exist_ok=True)

    # Define graph file path
    graph_file = os.path.join(brains_graph_dir, "code_graph.json")

    # Initialize empty graph
    graph = {
        "nodes": [],
        "edges": []
    }

    # Update the global graph file path
    GRAPH_FILE_PATH = graph_file

    # Save the initial graph
    with open(graph_file, "w") as f:
        json.dump(graph, f, indent=2)

    # Copy the graph viewer HTML file
    viewer_source = Path(__file__).parent.parent / "D3JS-UI" / "graph-viewer.html"
    viewer_dest = os.path.join(brains_graph_dir, "graph-viewer.html")

    try:
        shutil.copy2(viewer_source, viewer_dest)
        viewer_msg = f"\nViewer copied to: {viewer_dest}"
    except FileNotFoundError:
        viewer_msg = f"\nWarning: Could not find viewer at {viewer_source}"
    except Exception as e:
        viewer_msg = f"\nWarning: Could not copy viewer: {str(e)}"

    return f"Successfully initialized graph at: {graph_file}\nCodebase root: {abs_root}{viewer_msg}"


@mcp.tool()
def add_nodes(node_list: list[dict[str, Any]]) -> str:
    """
    Add nodes to the code graph.

    Args:
        node_list: List of nodes to add. Each node should have:
            - id (str): Unique identifier for the node (use full path for files to avoid clashes).
            If this is a class or function use path::name where name is the name of the class/function.
            - type (str): Node type - "class", "function", or "file"
            - metadata (dict): Type-specific metadata:
                - class: {"functions": [...], "attributes": [...], "children": [...]}
                - function: {"parameters": [...], "returns": "...", "brief_summary": "...", "full_documentation": "..."}
                - file: {"classes": [...], "functions": [...]}
            - highlight (int, optional): Color code for highlighting (0 = no highlight)

    Returns:
        str: Status message indicating success and number of nodes added/skipped
    """
    graph = load_graph()
    existing_ids = {node["id"] for node in graph["nodes"]}

    added_count = 0
    skipped_count = 0

    for node in node_list:
        # Validate required fields
        if "id" not in node or "type" not in node:
            continue

        # Skip if node already exists
        if node["id"] in existing_ids:
            skipped_count += 1
            continue

        # Ensure highlight field exists
        if "highlight" not in node:
            node["highlight"] = 0

        # Ensure metadata exists
        if "metadata" not in node:
            node["metadata"] = {}

        graph["nodes"].append(node)
        existing_ids.add(node["id"])
        added_count += 1

    save_graph(graph)

    return f"Added {added_count} node(s), skipped {skipped_count} existing node(s)."


@mcp.tool()
def add_edges(edge_list: list[dict[str, Any]]) -> str:
    """
    Add edges to the code graph.

    Args:
        edge_list: List of edges to add. Each edge should have:
            - source (str): ID of the source node
            - target (str): ID of the target node
            - type (str): Edge type - "inherit", "invokes", or "contains"
            - highlight (int, optional): Color code for highlighting (0 = no highlight)

    Returns:
        str: Status message indicating success and number of edges added/skipped
    """
    graph = load_graph()
    node_ids = {node["id"] for node in graph["nodes"]}

    # Create set of existing edges for deduplication
    existing_edges = {
        (edge["source"], edge["target"], edge["type"])
        for edge in graph["edges"]
    }

    added_count = 0
    skipped_count = 0

    for edge in edge_list:
        # Validate required fields
        if "source" not in edge or "target" not in edge or "type" not in edge:
            continue

        # Create edge signature
        edge_sig = (edge["source"], edge["target"], edge["type"])

        # Skip if edge already exists
        if edge_sig in existing_edges:
            skipped_count += 1
            continue

        # Optionally validate that source and target nodes exist
        if edge["source"] not in node_ids or edge["target"] not in node_ids:
            skipped_count += 1
            continue

        # Generate edge ID
        edge["id"] = get_next_edge_id(graph)

        # Ensure highlight field exists
        if "highlight" not in edge:
            edge["highlight"] = 0

        graph["edges"].append(edge)
        existing_edges.add(edge_sig)
        added_count += 1

    save_graph(graph)

    return f"Added {added_count} edge(s), skipped {skipped_count} existing/invalid edge(s)."


@mcp.tool()
def highlight_nodes(node_ids: list[str], color: int, question: str = "") -> str:
    """
    Highlight specific nodes in the graph.

    Args:
        node_ids: List of node IDs to highlight
        color: Color code as integer (0 = no highlight)
        question: Optional question/description associated with this highlight

    Returns:
        str: Status message indicating success and number of nodes highlighted
    """
    graph = load_graph()

    # Initialize highlightQuestions if not present
    if "highlightQuestions" not in graph:
        graph["highlightQuestions"] = {}

    # First, reset all highlights
    for node in graph["nodes"]:
        node["highlight"] = 0

    # Then apply new highlights
    highlighted_count = 0
    node_id_set = set(node_ids)

    for node in graph["nodes"]:
        if node["id"] in node_id_set:
            node["highlight"] = color
            highlighted_count += 1

    # Store the question for this color
    if question:
        graph["highlightQuestions"][str(color)] = question

    save_graph(graph)

    return f"Highlighted {highlighted_count} node(s) with color {color}."


@mcp.tool()
def highlight_edges(edge_ids: list[str], color: int, question: str = "") -> str:
    """
    Highlight specific edges in the graph.

    Args:
        edge_ids: List of edge IDs to highlight
        color: Color code as integer (0 = no highlight)
        question: Optional question/description associated with this highlight

    Returns:
        str: Status message indicating success and number of edges highlighted
    """
    graph = load_graph()

    # Initialize highlightQuestions if not present
    if "highlightQuestions" not in graph:
        graph["highlightQuestions"] = {}

    # First, reset all highlights
    for edge in graph["edges"]:
        edge["highlight"] = 0

    # Then apply new highlights
    highlighted_count = 0
    edge_id_set = set(edge_ids)

    for edge in graph["edges"]:
        if edge["id"] in edge_id_set:
            edge["highlight"] = color
            highlighted_count += 1

    # Store the question for this color
    if question:
        graph["highlightQuestions"][str(color)] = question

    save_graph(graph)

    return f"Highlighted {highlighted_count} edge(s) with color {color}."


@mcp.tool()
def read_graph() -> str:
    """
    Read and return the current state of the code graph.

    Returns:
        str: JSON string representation of the graph
    """
    graph = load_graph()
    return json.dumps(graph, indent=2)


if __name__ == "__main__":
    # Run the server
    mcp.run()
