"""
Graph core for ARC CLI.

Provides SQLite-backed knowledge graph operations including node/edge creation,
retrieval, and traversal.
"""

import json
from datetime import datetime, timedelta, timezone
import sqlite3
from typing import Any, Dict, List, Optional

BASE_DEMO_TIME = datetime(2026, 1, 1, 0, 0, 0, tzinfo=timezone.utc)


def get_project_clock(conn: sqlite3.Connection) -> Optional[float]:
    """Retrieve the current fake project clock hour if set in graph memory, else None."""
    cursor = conn.cursor()
    cursor.execute(
        """
        SELECT properties FROM nodes
        WHERE type = 'memory' AND label = 'project_clock'
        ORDER BY id DESC LIMIT 1
        """
    )
    row = cursor.fetchone()
    if not row or not row[0]:
        return None
    try:
        props = json.loads(row[0])
        if "current_hour" in props:
            return float(props["current_hour"])
    except (json.JSONDecodeError, TypeError, ValueError):
        pass
    return None


def set_project_clock(conn: sqlite3.Connection, current_hour: float) -> None:
    """Set or update the fake project clock hour in memory node."""
    cursor = conn.cursor()
    cursor.execute(
        """
        SELECT id, properties FROM nodes
        WHERE type = 'memory' AND label = 'project_clock'
        ORDER BY id DESC LIMIT 1
        """
    )
    row = cursor.fetchone()
    if row:
        node_id = row[0]
        try:
            props = json.loads(row[1]) if row[1] else {}
        except Exception:
            props = {}
        props["current_hour"] = current_hour
        update_node_properties(conn, node_id, props)
    else:
        props = {"current_hour": current_hour, "base_time": BASE_DEMO_TIME.isoformat()}
        add_node(conn, type="memory", label="project_clock", properties=props)


def get_current_time(conn: Optional[sqlite3.Connection] = None) -> datetime:
    """Returns fake project clock time if demo clock active in database, else real UTC time."""
    if conn is not None:
        try:
            hour = get_project_clock(conn)
            if hour is not None:
                return BASE_DEMO_TIME + timedelta(hours=hour)
        except Exception:
            pass
    return datetime.now(timezone.utc)


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
    created_at: Optional[str] = None,
) -> int:
    """Add a node to the knowledge graph.

    Args:
        conn: An active sqlite3 Connection object.
        type: The type of node (e.g. milestone, file, commit, decision, risk, nudge, memory).
        label: Human-readable label for the node.
        properties: Type-specific key-value pairs stored as JSON.
        created_at: Optional explicit ISO timestamp string. Defaults to get_current_time(conn).

    Returns:
        The integer ID of the created node.
    """
    if properties is None:
        properties = {}

    properties_json = json.dumps(properties)
    if created_at is None:
        created_at = get_current_time(conn).isoformat()

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
    created_at: Optional[str] = None,
) -> int:
    """Add a directed edge between two nodes in the knowledge graph.

    Args:
        conn: An active sqlite3 Connection object.
        source_id: ID of the source node.
        target_id: ID of the target node.
        relation: Relation type (e.g. depends_on, touches, resolves, causes, blocks, decided_by, links_to).
        created_at: Optional explicit ISO timestamp string. Defaults to get_current_time(conn).

    Returns:
        The integer ID of the created edge.
    """
    if created_at is None:
        created_at = get_current_time(conn).isoformat()

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


def update_node_properties(
    conn: sqlite3.Connection,
    node_id: int,
    properties: Dict[str, Any],
) -> None:
    """Update the properties JSON blob of an existing node.

    Args:
        conn: An active sqlite3 Connection object.
        node_id: ID of the node to update.
        properties: Key-value pairs to store as JSON.
    """
    properties_json = json.dumps(properties)
    cursor = conn.cursor()
    cursor.execute(
        "UPDATE nodes SET properties = ? WHERE id = ?",
        (properties_json, node_id),
    )
    conn.commit()


def find_nodes(
    conn: sqlite3.Connection,
    type: Optional[str] = None,
    label: Optional[str] = None,
) -> List[Dict[str, Any]]:
    """Search for nodes matching the specified type and/or label.

    Args:
        conn: An active sqlite3 Connection object.
        type: Optional node type to filter by.
        label: Optional node label to filter by.

    Returns:
        List of matching node dictionaries.
    """
    query = "SELECT id, type, label, properties, created_at FROM nodes WHERE 1=1"
    params: List[Any] = []

    if type is not None:
        query += " AND type = ?"
        params.append(type)
    if label is not None:
        query += " AND label = ?"
        params.append(label)

    cursor = conn.cursor()
    cursor.execute(query, params)
    rows = cursor.fetchall()

    nodes = []
    for row in rows:
        raw_props = row[3]
        try:
            properties = json.loads(raw_props) if raw_props else {}
        except (json.JSONDecodeError, TypeError):
            properties = {}
        nodes.append(
            {
                "id": row[0],
                "type": row[1],
                "label": row[2],
                "properties": properties,
                "created_at": row[4],
            }
        )
    return nodes


def get_latest_context(conn: sqlite3.Connection) -> str:
    """Fetch the ingested_context memory node and return its content string.

    Args:
        conn: An active sqlite3 Connection object.

    Returns:
        The concatenated context content string, or an empty string if not found.
    """
    cursor = conn.cursor()
    cursor.execute(
        """
        SELECT properties FROM nodes
        WHERE type = 'memory' AND label = 'ingested_context'
        ORDER BY id DESC LIMIT 1
        """
    )
    row = cursor.fetchone()
    if not row or not row[0]:
        return ""

    try:
        props = json.loads(row[0])
        return props.get("content", "")
    except (json.JSONDecodeError, TypeError):
        return ""

