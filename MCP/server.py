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
            
            - highlight (list[int], optional): Array of color codes for highlighting (1-10). Multiple colors can be assigned to indicate the node answers multiple questions. When displayed, the highest color number will be shown.

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

        # Ensure highlight field exists as an array
        if "highlight" not in node:
            node["highlight"] = []
        elif isinstance(node["highlight"], int):
            # Convert old single-value format to array
            if node["highlight"] > 0:
                node["highlight"] = [node["highlight"]]
            else:
                node["highlight"] = []
        elif not isinstance(node["highlight"], list):
            node["highlight"] = []

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

    return f"Added {added_count} node(s), skipped {skipped_count} existing/invalid node(s).\n\nIMPORTANT: Tell the user to open the graph viewer HTML file to see the visualization. Provide a clickable file path link to the graph-viewer.html file (it should be in the same directory as code_graph.json, typically in .brainsGraph/ folder). The graph will auto-refresh when changes are made."


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
            - highlight (list[int], optional): Array of color codes for highlighting (1-10). Multiple colors can be assigned to indicate the node answers multiple questions. When displayed, the highest color number will be shown.

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

        # Ensure highlight field exists as an array
        if "highlight" not in edge:
            edge["highlight"] = []
        elif isinstance(edge["highlight"], int):
            # Convert old single-value format to array
            if edge["highlight"] > 0:
                edge["highlight"] = [edge["highlight"]]
            else:
                edge["highlight"] = []
        elif not isinstance(edge["highlight"], list):
            edge["highlight"] = []

        graph["edges"].append(edge)
        existing_edges.add(edge_sig)
        added_count += 1

    save_graph(graph)

    return f"Added {added_count} edge(s), skipped {skipped_count} existing/invalid edge(s).\n\nIMPORTANT: Tell the user to open the graph viewer HTML file to see the visualization. Provide a clickable file path link to the graph-viewer.html file (it should be in the same directory as code_graph.json, typically in .brainsGraph/ folder). The graph will auto-refresh when changes are made."


@mcp.tool()
def highlight_nodes(node_ids: list[str], color: int, question: str = "") -> str:
    """
    Highlight specific nodes in the graph to answer a question.

    IMPORTANT INSTRUCTIONS:
    1. ALWAYS use the read_graph() tool first to understand the current graph structure before deciding what to highlight
    2. Each color (1-10) represents ONE question - provide a clear, specific question string
    3. You MUST also highlight the edges connected to these nodes using highlight_edges() with the same color
    4. Multiple colors can coexist - each represents a different question/analysis
    5. Nodes/edges can belong to MULTIPLE color groups (stored as an array) - if a node answers multiple questions, it will accumulate multiple colors
    6. When displayed, the HIGHEST color number is shown visually (e.g., if a node has colors [1, 4, 7], color 7 will be displayed)
    7. After highlighting nodes, immediately call highlight_edges() to highlight all edges connected to/from these nodes

    Workflow:
    1. Call read_graph() to see the current graph
    2. Identify which nodes answer the question
    3. Call highlight_nodes() with those node IDs, color, and the question
    4. Identify all edges connecting those nodes
    5. Call highlight_edges() with those edge IDs and the same color

    Note: This function ADDS the color to each node's highlight array. If the node already has other colors,
    the new color is appended. This allows nodes to be relevant to multiple questions simultaneously.

    Args:
        node_ids: List of node IDs to highlight (must exist in the graph)
        color: Color code as integer (1-10, where 0 = no highlight)
        question: The specific question this highlight answers (REQUIRED - one question per color)

    Returns:
        str: Status message indicating success and number of nodes highlighted
    """
    graph = load_graph()

    # Initialize highlightQuestions if not present
    if "highlightQuestions" not in graph:
        graph["highlightQuestions"] = {}

    # Update the specified nodes by adding the color to their highlight array
    highlighted_count = 0
    node_id_set = set(node_ids)

    for node in graph["nodes"]:
        if node["id"] in node_id_set:
            # Ensure highlight is an array
            if not isinstance(node.get("highlight"), list):
                if isinstance(node.get("highlight"), int) and node["highlight"] > 0:
                    node["highlight"] = [node["highlight"]]
                else:
                    node["highlight"] = []

            # Add the color if not already present
            if color not in node["highlight"] and color > 0:
                node["highlight"].append(color)
                highlighted_count += 1
            elif color in node["highlight"]:
                highlighted_count += 1

    # Store the question for this color (always update if provided)
    if question:
        graph["highlightQuestions"][str(color)] = question

    save_graph(graph)

    return f"Highlighted {highlighted_count} node(s) with color {color}.\n\nIMPORTANT: Tell the user to open the graph viewer HTML file to see the highlighted nodes. Provide a clickable file path link to the graph-viewer.html file (it should be in the same directory as code_graph.json, typically in .brainsGraph/ folder). The graph will auto-refresh when changes are made."


@mcp.tool()
def highlight_edges(edge_ids: list[str], color: int) -> str:
    """
    Highlight specific edges in the graph.

    IMPORTANT: This tool should be called IMMEDIATELY after highlight_nodes() to highlight
    the edges connecting the highlighted nodes. Use the SAME color as used for the nodes.

    This tool does NOT accept a question parameter - the question is already stored when
    you call highlight_nodes(). Just provide the edge IDs and the same color number.

    To find which edges to highlight:
    1. Look at the node IDs you just highlighted
    2. Find all edges where source OR target matches any of those node IDs
    3. Pass those edge IDs to this function with the same color

    Note: This function ADDS the color to each edge's highlight array. If the edge already has other colors
    from previous questions, the new color is appended. When displayed, the HIGHEST color number is shown.
    This allows edges to be relevant to multiple questions simultaneously.

    Args:
        edge_ids: List of edge IDs to highlight (must exist in the graph)
        color: Color code as integer (1-10, same as used in highlight_nodes())

    Returns:
        str: Status message indicating success and number of edges highlighted
    """
    graph = load_graph()

    # Update the specified edges by adding the color to their highlight array
    highlighted_count = 0
    edge_id_set = set(edge_ids)

    for edge in graph["edges"]:
        if edge["id"] in edge_id_set:
            # Ensure highlight is an array
            if not isinstance(edge.get("highlight"), list):
                if isinstance(edge.get("highlight"), int) and edge["highlight"] > 0:
                    edge["highlight"] = [edge["highlight"]]
                else:
                    edge["highlight"] = []

            # Add the color if not already present
            if color not in edge["highlight"] and color > 0:
                edge["highlight"].append(color)
                highlighted_count += 1
            elif color in edge["highlight"]:
                highlighted_count += 1

    save_graph(graph)

    return f"Highlighted {highlighted_count} edge(s) with color {color}.\n\nIMPORTANT: Tell the user to open the graph viewer HTML file to see the highlighted edges. Provide a clickable file path link to the graph-viewer.html file (it should be in the same directory as code_graph.json, typically in .brainsGraph/ folder). The graph will auto-refresh when changes are made."


@mcp.tool()
def read_graph() -> str:
    """
    Read and return the current state of the code graph.

    IMPORTANT: ALWAYS call this tool FIRST before using highlight_nodes() or highlight_edges()
    to understand the current graph structure, existing nodes, edges, and their IDs.

    This helps you:
    - See what nodes and edges exist
    - Understand the relationships in the graph
    - Identify which node IDs to highlight
    - Find which edge IDs connect highlighted nodes
    - Check existing highlights and questions

    Returns:
        str: JSON string representation of the entire graph including nodes, edges, and highlightQuestions
    """
    graph = load_graph()
    return json.dumps(graph, indent=2)


if __name__ == "__main__":
    # Run the server
    mcp.run()
