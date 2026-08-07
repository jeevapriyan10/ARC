import sqlite3
import pytest

from arc_cli.graph import (
    init_graph_schema,
    add_node,
    add_edge,
    get_node,
    get_edges_from,
    get_edges_to,
    traverse_dependents,
)


@pytest.fixture
def db_conn():
    conn = sqlite3.connect(":memory:")
    init_graph_schema(conn)
    yield conn
    conn.close()


def test_init_schema_idempotence(db_conn):
    # Calling init_graph_schema again should not throw errors
    init_graph_schema(db_conn)
    cursor = db_conn.cursor()
    cursor.execute("SELECT name FROM sqlite_master WHERE type='table'")
    tables = {row[0] for row in cursor.fetchall()}
    assert "nodes" in tables
    assert "edges" in tables


def test_add_and_get_node(db_conn):
    props = {
        "owner": "Alice",
        "deadline": "2026-12-31",
        "status": "in_progress",
    }
    node_id = add_node(db_conn, type="milestone", label="M1: Core Graph", properties=props)
    assert isinstance(node_id, int)

    node = get_node(db_conn, node_id)
    assert node is not None
    assert node["id"] == node_id
    assert node["type"] == "milestone"
    assert node["label"] == "M1: Core Graph"
    assert node["properties"] == props
    assert "created_at" in node


def test_get_nonexistent_node(db_conn):
    assert get_node(db_conn, 999) is None


def test_add_and_get_edges(db_conn):
    n1 = add_node(db_conn, type="milestone", label="M1", properties={"owner": "A"})
    n2 = add_node(db_conn, type="milestone", label="M2", properties={"owner": "B"})
    n3 = add_node(db_conn, type="commit", label="Commit 1", properties={"hash": "abc"})

    e1 = add_edge(db_conn, source_id=n2, target_id=n1, relation="depends_on")
    e2 = add_edge(db_conn, source_id=n3, target_id=n2, relation="touches")

    outgoing_n2 = get_edges_from(db_conn, n2)
    assert len(outgoing_n2) == 1
    assert outgoing_n2[0]["id"] == e1
    assert outgoing_n2[0]["target_id"] == n1
    assert outgoing_n2[0]["relation"] == "depends_on"

    incoming_n1 = get_edges_to(db_conn, n1)
    assert len(incoming_n1) == 1
    assert incoming_n1[0]["id"] == e1
    assert incoming_n1[0]["source_id"] == n2

    # Filtered by relation
    assert len(get_edges_from(db_conn, n2, relation="depends_on")) == 1
    assert len(get_edges_from(db_conn, n2, relation="resolves")) == 0
    assert len(get_edges_to(db_conn, n1, relation="depends_on")) == 1
    assert len(get_edges_to(db_conn, n1, relation="touches")) == 0


def test_traverse_dependents(db_conn):
    # Setup graph: M1 <- M2 <- M3
    #              M1 <- M4
    # M2 depends on M1
    # M3 depends on M2
    # M4 depends on M1
    m1 = add_node(db_conn, type="milestone", label="M1")
    m2 = add_node(db_conn, type="milestone", label="M2")
    m3 = add_node(db_conn, type="milestone", label="M3")
    m4 = add_node(db_conn, type="milestone", label="M4")
    unrelated = add_node(db_conn, type="milestone", label="Unrelated")

    add_edge(db_conn, source_id=m2, target_id=m1, relation="depends_on")
    add_edge(db_conn, source_id=m3, target_id=m2, relation="depends_on")
    add_edge(db_conn, source_id=m4, target_id=m1, relation="depends_on")
    add_edge(db_conn, source_id=unrelated, target_id=m1, relation="links_to")

    dependents_m1 = traverse_dependents(db_conn, m1)
    dep_ids = {d["id"] for d in dependents_m1}
    assert dep_ids == {m2, m3, m4}
    assert unrelated not in dep_ids

    dependents_m2 = traverse_dependents(db_conn, m2)
    dep_ids_m2 = {d["id"] for d in dependents_m2}
    assert dep_ids_m2 == {m3}

    dependents_m3 = traverse_dependents(db_conn, m3)
    assert dependents_m3 == []
