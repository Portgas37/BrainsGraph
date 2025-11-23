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
        graph = {"nodes": [], "edges": []}
        save_graph(graph)
        return graph

    with open(GRAPH_FILE_PATH, "r") as f:
        return json.load(f)


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
    
    Nodes represent code elements: classes, functions, or files. The agent creates nodes
    for elements relevant to understanding the overall code structure. Nodes are identified
    by a unique ID with the element's name.

    Args:
        node_list: List of nodes to add. Each node must have:
            - id (str): Unique identifier for the node (e.g., "src/utils.py:MyClass" or "src/main.py:my_function")
            - label (str): Display name for the node
            - type (str): Node type - "file", "class", or "function"
            - metadata (dict): Type-specific metadata containing field names (clickable to show content):
                
                For "file" nodes:
                - classes (list[str]): Names of classes defined in the file
                - functions (list[str]): Top-level functions in the file (not inner functions)
                - brief_summary (str): Brief description of the file's purpose
                
                For "class" nodes:
                - functions (list[str]): Method names defined in the class
                - attributes (list[str]): Attribute/property names of the class
                - children (list[str]): Names of child classes (if applicable)
                - brief_summary (str): Brief description of the class
                
                For "function" nodes:
                - parameters (list[str]): Parameter names and types
                - returns (str): Description of return value(s)
                - brief_summary (str): Brief description of what the function does
                - full_documentation (str): Complete function documentation/docstring
            
            - highlight (int, optional): Color code for highlighting (0-10, where 0 = no highlight)

    Returns:
        str: Status message indicating success and number of nodes added/skipped
    """
    graph = load_graph()
    existing_ids = {node["id"] for node in graph["nodes"]}

    added_count = 0
    skipped_count = 0
    
    # Valid source code file extensions
    VALID_EXTENSIONS = {'.py', '.js', '.ts', '.java', '.cpp', '.c', '.h', '.hpp', 
                       '.cs', '.rb', '.go', '.rs', '.php', '.swift', '.kt'}

    for node in node_list:
        # Validate required fields
        if "id" not in node or "type" not in node:
            continue

        # Skip if node already exists
        if node["id"] in existing_ids:
            skipped_count += 1
            continue
        
        # Validate node type
        node_type = node.get("type", "").lower()
        if node_type not in ["file", "class", "function"]:
            skipped_count += 1
            continue
        
        # For file nodes, validate that they are source code files
        if node_type == "file":
            file_path = node.get("id", "")
            # Check if file has a valid source code extension
            has_valid_ext = any(file_path.endswith(ext) for ext in VALID_EXTENSIONS)
            if not has_valid_ext:
                skipped_count += 1
                continue

        # Ensure label exists (use id as fallback)
        if "label" not in node:
            node["label"] = node["id"].split(":")[-1] if ":" in node["id"] else node["id"]

        # Ensure highlight field exists and is valid
        if "highlight" not in node:
            node["highlight"] = 0
        else:
            node["highlight"] = max(0, min(10, int(node["highlight"])))

        # Ensure metadata exists
        if "metadata" not in node:
            node["metadata"] = {}
        
        # Validate metadata structure based on node type
        metadata = node.get("metadata", {})
        
        if node_type == "file":
            # File metadata should contain lists of classes and functions
            if "classes" not in metadata:
                metadata["classes"] = []
            if "functions" not in metadata:
                metadata["functions"] = []
            # brief_summary is optional
                
        elif node_type == "class":
            # Class metadata should contain method and attribute names
            if "functions" not in metadata:
                metadata["functions"] = []
            if "attributes" not in metadata:
                metadata["attributes"] = []
            # children and brief_summary are optional
                
        elif node_type == "function":
            # Function metadata should document parameters, return type, and documentation
            if "parameters" not in metadata:
                metadata["parameters"] = []
            # returns, brief_summary, and full_documentation are optional

        graph["nodes"].append(node)
        existing_ids.add(node["id"])
        added_count += 1

    save_graph(graph)

    return f"Added {added_count} node(s), skipped {skipped_count} existing/invalid node(s)."


@mcp.tool()
def add_edges(edge_list: list[dict[str, Any]]) -> str:
    """
    Add edges (relationships) to the code graph.
    
    Edges represent relationships between nodes and help visualize how code elements
    interact. The agent creates edges when necessary to understand code flow and dependencies.

    Args:
        edge_list: List of edges to add. Each edge must have:
            - source (str): ID of the source node
            - target (str): ID of the target node
            - type (str): Edge type indicating the relationship:
                - "inherit": Class inheritance (source class inherits from target class)
                - "invokes": Function invocation (source function calls target function)
                - "contains": Containment relationship (source file/class contains target element)
            - highlight (int, optional): Color code for highlighting (0-10, where 0 = no highlight)

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
    
    # Valid edge types
    VALID_EDGE_TYPES = {"inherit", "invokes", "contains"}

    for edge in edge_list:
        # Validate required fields
        if "source" not in edge or "target" not in edge or "type" not in edge:
            continue
        
        # Validate edge type
        edge_type = edge.get("type", "").lower()
        if edge_type not in VALID_EDGE_TYPES:
            skipped_count += 1
            continue

        # Create edge signature
        edge_sig = (edge["source"], edge["target"], edge_type)

        # Skip if edge already exists
        if edge_sig in existing_edges:
            skipped_count += 1
            continue

        # Validate that source and target nodes exist
        if edge["source"] not in node_ids or edge["target"] not in node_ids:
            skipped_count += 1
            continue

        # Generate edge ID
        edge["id"] = get_next_edge_id(graph)
        
        # Normalize edge type
        edge["type"] = edge_type

        # Ensure highlight field exists and is valid
        if "highlight" not in edge:
            edge["highlight"] = 0
        else:
            edge["highlight"] = max(0, min(10, int(edge["highlight"])))

        graph["edges"].append(edge)
        existing_edges.add(edge_sig)
        added_count += 1

    save_graph(graph)

    return f"Added {added_count} edge(s), skipped {skipped_count} existing/invalid edge(s)."


@mcp.tool()
def highlight_nodes(node_ids: list[str], color: int) -> str:
    """
    Highlight specific nodes in the graph.

    Args:
        node_ids: List of node IDs to highlight
        color: Color code as integer (0 = no highlight)

    Returns:
        str: Status message indicating success and number of nodes highlighted
    """
    graph = load_graph()

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

    save_graph(graph)

    return f"Highlighted {highlighted_count} node(s) with color {color}."


@mcp.tool()
def highlight_edges(edge_ids: list[str], color: int) -> str:
    """
    Highlight specific edges in the graph.

    Args:
        edge_ids: List of edge IDs to highlight
        color: Color code as integer (0 = no highlight)

    Returns:
        str: Status message indicating success and number of edges highlighted
    """
    graph = load_graph()

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
