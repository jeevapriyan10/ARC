from datetime import datetime, timedelta, timezone
import sqlite3
from typer.testing import CliRunner

from arc_cli.gate import (
    materiality,
    run_gate,
    specificity,
    timing,
)
from arc_cli.graph import (
    add_edge,
    add_node,
    find_nodes,
    get_edges_from,
    get_node,
    init_graph_schema,
)
from arc_cli.main import app

runner = CliRunner()


def test_materiality_cases(tmp_path):
    db_path = tmp_path / "arc.db"
    conn = sqlite3.connect(db_path)
    init_graph_schema(conn)

    now = datetime.now(timezone.utc)
    old_time = (now - timedelta(hours=10)).isoformat()
    recent_time = (now - timedelta(minutes=10)).isoformat()

    # Milestone 1: Overdue (created 10h ago, 2h deadline), 0 dependents
    m1_id = add_node(
        conn,
        type="milestone",
        label="Auth Module",
        properties={"deadline_hours": 2, "owner": "Alice", "status": "in_progress"},
    )
    # Update created_at
    conn.cursor().execute("UPDATE nodes SET created_at = ? WHERE id = ?", (old_time, m1_id))
    conn.commit()

    r1_id = add_node(
        conn,
        type="risk",
        label="Overdue: Auth Module",
        properties={"signal": "milestone_overdue", "milestone_id": m1_id, "resolved": False},
    )
    add_edge(conn, source_id=m1_id, target_id=r1_id, relation="causes")

    # Case A: 0 dependents but deadline passed -> Materiality True
    mat1, reason1 = materiality(conn, r1_id)
    assert mat1 is True
    assert "deadline has passed" in reason1

    # Milestone 2 & 3: M2 (recent, 10h deadline) -> M3 depends on M2 (1 dependent)
    m2_id = add_node(
        conn,
        type="milestone",
        label="API Core",
        properties={"deadline_hours": 10, "owner": "Bob", "status": "not_started"},
    )
    conn.cursor().execute("UPDATE nodes SET created_at = ? WHERE id = ?", (recent_time, m2_id))
    conn.commit()

    m3_id = add_node(
        conn,
        type="milestone",
        label="Frontend Integration",
        properties={"deadline_hours": 20, "owner": "Charlie", "status": "not_started"},
    )
    add_edge(conn, source_id=m3_id, target_id=m2_id, relation="depends_on")

    r2_id = add_node(
        conn,
        type="risk",
        label="Stalled: API Core",
        properties={"signal": "milestone_overdue", "milestone_id": m2_id, "resolved": False},
    )
    add_edge(conn, source_id=m2_id, target_id=r2_id, relation="causes")

    # Case B: 1 dependent, deadline not yet passed -> Materiality True
    mat2, reason2 = materiality(conn, r2_id)
    assert mat2 is True
    assert "1 dependent milestone(s)" in reason2

    # Milestone 4: Recent (deadline not passed), 0 dependents
    m4_id = add_node(
        conn,
        type="milestone",
        label="Docs",
        properties={"deadline_hours": 10, "owner": "Dave", "status": "not_started"},
    )
    conn.cursor().execute("UPDATE nodes SET created_at = ? WHERE id = ?", (recent_time, m4_id))
    conn.commit()

    r4_id = add_node(
        conn,
        type="risk",
        label="Behind: Docs",
        properties={"signal": "milestone_overdue", "milestone_id": m4_id, "resolved": False},
    )
    add_edge(conn, source_id=m4_id, target_id=r4_id, relation="causes")

    # Case C: 0 dependents, deadline not passed -> Materiality False
    mat4, reason4 = materiality(conn, r4_id)
    assert mat4 is False
    assert "0 dependents and deadline has not passed" in reason4

    conn.close()


def test_specificity_cases(tmp_path):
    db_path = tmp_path / "arc.db"
    conn = sqlite3.connect(db_path)
    init_graph_schema(conn)

    # Specific risk linked to milestone
    m_id = add_node(
        conn,
        type="milestone",
        label="Database Schema",
        properties={"deadline_hours": 5, "owner": "Alice", "status": "in_progress"},
    )
    r_spec_id = add_node(
        conn,
        type="risk",
        label="Overdue: Database Schema",
        properties={"signal": "milestone_overdue", "milestone_id": m_id, "resolved": False},
    )
    add_edge(conn, source_id=m_id, target_id=r_spec_id, relation="causes")

    spec1, reason1 = specificity(conn, r_spec_id)
    assert spec1 is True
    assert "Database Schema" in reason1

    # Vague risk with no milestone
    r_vague_id = add_node(
        conn,
        type="risk",
        label="Vague drift warning",
        properties={"signal": "commit_silence", "resolved": False},
    )
    spec2, reason2 = specificity(conn, r_vague_id)
    assert spec2 is False
    assert "Vague risk signal" in reason2

    conn.close()


def test_timing_and_repeat_gate_runs(tmp_path):
    db_path = tmp_path / "arc.db"
    conn = sqlite3.connect(db_path)
    init_graph_schema(conn)

    now = datetime.now(timezone.utc)
    old_time = (now - timedelta(hours=5)).isoformat()

    # Milestone M_main with 1 dependent M_dep and passed deadline
    m_main = add_node(
        conn,
        type="milestone",
        label="Core Engine",
        properties={"deadline_hours": 2, "owner": "Alice", "status": "in_progress"},
    )
    conn.cursor().execute("UPDATE nodes SET created_at = ? WHERE id = ?", (old_time, m_main))

    m_dep = add_node(
        conn,
        type="milestone",
        label="CLI UI",
        properties={"deadline_hours": 10, "owner": "Bob", "status": "not_started"},
    )
    add_edge(conn, source_id=m_dep, target_id=m_main, relation="depends_on")

    r_id = add_node(
        conn,
        type="risk",
        label="Overdue: Core Engine",
        properties={"signal": "milestone_overdue", "milestone_id": m_main, "resolved": False},
    )
    add_edge(conn, source_id=m_main, target_id=r_id, relation="causes")

    # Run 1: Gate should FIRE (Materiality: True, Timing: True, Specificity: True)
    d1 = run_gate(conn, r_id, hours=4.0)
    assert d1["final_verdict"] is True
    assert d1["materiality_result"] is True
    assert d1["timing_result"] is True
    assert d1["specificity_result"] is True

    # Run 2: Immediate repeat run within timing window -> Timing FAIL -> Gate STAY SILENT
    d2 = run_gate(conn, r_id, hours=4.0)
    assert d2["final_verdict"] is False
    assert d2["timing_result"] is False
    assert "already fired" in d2["timing_reasoning"]

    # Verify decision nodes logged
    decisions = find_nodes(conn, type="decision")
    assert len(decisions) == 2

    # Verify decided_by edges
    edges_d1 = get_edges_from(conn, d1["id"], relation="decided_by")
    assert len(edges_d1) == 1
    assert edges_d1[0]["target_id"] == r_id

    edges_d2 = get_edges_from(conn, d2["id"], relation="decided_by")
    assert len(edges_d2) == 1
    assert edges_d2[0]["target_id"] == r_id

    conn.close()


def test_status_cli_integration(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    arc_dir = tmp_path / ".arc"
    arc_dir.mkdir()
    db_path = arc_dir / "arc.db"

    conn = sqlite3.connect(db_path)
    init_graph_schema(conn)

    now = datetime.now(timezone.utc)
    old_time = (now - timedelta(hours=10)).isoformat()

    m_id = add_node(
        conn,
        type="milestone",
        label="Backend Server",
        properties={"deadline_hours": 2, "owner": "Eve", "status": "in_progress"},
    )
    conn.cursor().execute("UPDATE nodes SET created_at = ? WHERE id = ?", (old_time, m_id))
    conn.commit()
    conn.close()

    result = runner.invoke(app, ["status"])
    assert result.exit_code == 0
    assert "ARC Intervention Gate Decisions" in result.output
    assert "FIRE NUDGE" in result.output
