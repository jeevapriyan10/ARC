"""
Graph core for ARC CLI.

Provides SQLite-backed knowledge graph operations including node/edge creation,
retrieval, and traversal.
"""

import json
from datetime import datetime, timezone
import sqlite3
from typing import Any, Dict, List, Optional


def init_graph_schema(conn: sqlite3.Connection) -> None:
    """Initialize the graph database schema if it does not already exist.

    Creates the `nodes` and `edges` tables with appropriate constraints.
    Idempotent operation.

    Args:
        conn: An active sqlite3 Connection object.
    """
    cursor = conn.cursor()
    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS nodes (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            type TEXT NOT NULL,
            label TEXT NOT NULL,
            properties TEXT,
            created_at TEXT NOT NULL
        )
        """
    )
    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS edges (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            source_id INTEGER NOT NULL,
            target_id INTEGER NOT NULL,
            relation TEXT NOT NULL,
            created_at TEXT NOT NULL,
            FOREIGN KEY (source_id) REFERENCES nodes(id) ON DELETE CASCADE,
            FOREIGN KEY (target_id) REFERENCES nodes(id) ON DELETE CASCADE
        )
        """
    )
    conn.commit()


def add_node(
    conn: sqlite3.Connection,
    type: str,
    label: str,
    properties: Optional[Dict[str, Any]] = None,
) -> int:
    """Add a node to the knowledge graph.

    Args:
        conn: An active sqlite3 Connection object.
        type: The type of node (e.g. milestone, file, commit, decision, risk, nudge, memory).
        label: Human-readable label for the node.
        properties: Type-specific key-value pairs stored as JSON.

    Returns:
        The integer ID of the created node.
    """
    if properties is None:
        properties = {}

    properties_json = json.dumps(properties)
    created_at = datetime.now(timezone.utc).isoformat()

    cursor = conn.cursor()
    cursor.execute(
        """
        INSERT INTO nodes (type, label, properties, created_at)
        VALUES (?, ?, ?, ?)
        """,
        (type, label, properties_json, created_at),
    )
    conn.commit()
    return cursor.lastrowid


def add_edge(
    conn: sqlite3.Connection,
    source_id: int,
    target_id: int,
    relation: str,
) -> int:
    """Add a directed edge between two nodes in the knowledge graph.

    Args:
        conn: An active sqlite3 Connection object.
        source_id: ID of the source node.
        target_id: ID of the target node.
        relation: Relation type (e.g. depends_on, touches, resolves, causes, blocks, decided_by, links_to).

    Returns:
        The integer ID of the created edge.
    """
    created_at = datetime.now(timezone.utc).isoformat()

    cursor = conn.cursor()
    cursor.execute(
        """
        INSERT INTO edges (source_id, target_id, relation, created_at)
        VALUES (?, ?, ?, ?)
        """,
        (source_id, target_id, relation, created_at),
    )
    conn.commit()
    return cursor.lastrowid


def get_node(conn: sqlite3.Connection, node_id: int) -> Optional[Dict[str, Any]]:
    """Retrieve a node by its ID, with properties decoded from JSON.

    Args:
        conn: An active sqlite3 Connection object.
        node_id: ID of the node to retrieve.

    Returns:
        Dict representing node data, or None if not found.
    """
    cursor = conn.cursor()
    cursor.execute(
        "SELECT id, type, label, properties, created_at FROM nodes WHERE id = ?",
        (node_id,),
    )
    row = cursor.fetchone()
    if not row:
        return None

    raw_props = row[3]
    try:
        properties = json.loads(raw_props) if raw_props else {}
    except (json.JSONDecodeError, TypeError):
        properties = {}

    return {
        "id": row[0],
        "type": row[1],
        "label": row[2],
        "properties": properties,
        "created_at": row[4],
    }


def get_edges_from(
    conn: sqlite3.Connection,
    node_id: int,
    relation: Optional[str] = None,
) -> List[Dict[str, Any]]:
    """Retrieve all outgoing edges originating from the specified node.

    Args:
        conn: An active sqlite3 Connection object.
        node_id: ID of the source node.
        relation: Optional relation type to filter by.

    Returns:
        List of dictionaries representing outgoing edges.
    """
    cursor = conn.cursor()
    if relation:
        cursor.execute(
            """
            SELECT id, source_id, target_id, relation, created_at
            FROM edges
            WHERE source_id = ? AND relation = ?
            """,
            (node_id, relation),
        )
    else:
        cursor.execute(
            """
            SELECT id, source_id, target_id, relation, created_at
            FROM edges
            WHERE source_id = ?
            """,
            (node_id,),
        )

    rows = cursor.fetchall()
    return [
        {
            "id": row[0],
            "source_id": row[1],
            "target_id": row[2],
            "relation": row[3],
            "created_at": row[4],
        }
        for row in rows
    ]


def get_edges_to(
    conn: sqlite3.Connection,
    node_id: int,
    relation: Optional[str] = None,
) -> List[Dict[str, Any]]:
    """Retrieve all incoming edges targeting the specified node.

    Args:
        conn: An active sqlite3 Connection object.
        node_id: ID of the target node.
        relation: Optional relation type to filter by.

    Returns:
        List of dictionaries representing incoming edges.
    """
    cursor = conn.cursor()
    if relation:
        cursor.execute(
            """
            SELECT id, source_id, target_id, relation, created_at
            FROM edges
            WHERE target_id = ? AND relation = ?
            """,
            (node_id, relation),
        )
    else:
        cursor.execute(
            """
            SELECT id, source_id, target_id, relation, created_at
            FROM edges
            WHERE target_id = ?
            """,
            (node_id,),
        )

    rows = cursor.fetchall()
    return [
        {
            "id": row[0],
            "source_id": row[1],
            "target_id": row[2],
            "relation": row[3],
            "created_at": row[4],
        }
        for row in rows
    ]


def traverse_dependents(conn: sqlite3.Connection, node_id: int) -> List[Dict[str, Any]]:
    """Recursively walk 'depends_on' edges to find all nodes that depend on this node.

    A node B depends on node A if there is an edge where source_id = B, target_id = A,
    and relation = 'depends_on'. This function traverses multiple hops transitively.

    Args:
        conn: An active sqlite3 Connection object.
        node_id: ID of the node to find dependents for.

    Returns:
        List of node dictionaries for all direct and transitive dependents.
    """
    visited = set()
    dependents = []
    queue = [node_id]

    while queue:
        current_id = queue.pop(0)
        incoming_edges = get_edges_to(conn, current_id, relation="depends_on")
        for edge in incoming_edges:
            dependent_id = edge["source_id"]
            if dependent_id not in visited:
                visited.add(dependent_id)
                queue.append(dependent_id)
                dep_node = get_node(conn, dependent_id)
                if dep_node is not None:
                    dependents.append(dep_node)

    return dependents
