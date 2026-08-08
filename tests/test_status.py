from datetime import datetime, timedelta, timezone
import sqlite3
from typer.testing import CliRunner

from arc_cli.main import app
from arc_cli.graph import (
    init_graph_schema,
    add_node,
    find_nodes,
    get_edges_from,
)

runner = CliRunner()


def test_status_no_database(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    result = runner.invoke(app, ["status"])
    assert result.exit_code == 1
    assert "Database not found" in result.output


def test_status_no_milestones(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    runner.invoke(app, ["init"])
    result = runner.invoke(app, ["status"])
    assert result.exit_code == 0
    assert "No milestones found in graph." in result.output


def test_status_normal_ok(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    arc_dir = tmp_path / ".arc"
    arc_dir.mkdir()
    db_path = arc_dir / "arc.db"

    conn = sqlite3.connect(db_path)
    init_graph_schema(conn)

    # Created 1 hour ago with 10 hr deadline
    now = datetime.now(timezone.utc)
    created_at = (now - timedelta(hours=1)).isoformat()

    cursor = conn.cursor()
    cursor.execute(
        "INSERT INTO nodes (type, label, properties, created_at) VALUES (?, ?, ?, ?)",
        ("milestone", "Database Schema", '{"owner": "Alice", "deadline_hours": 10, "status": "not_started"}', created_at),
    )
    conn.commit()
    conn.close()

    result = runner.invoke(app, ["status"])
    assert result.exit_code == 0
    assert "Database Schema" in result.output
    assert "No active risks detected." in result.output


def test_status_overdue_risk_and_idempotency(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    arc_dir = tmp_path / ".arc"
    arc_dir.mkdir()
    db_path = arc_dir / "arc.db"

    conn = sqlite3.connect(db_path)
    init_graph_schema(conn)

    # Created 10 hours ago with 2 hr deadline -> Overdue
    now = datetime.now(timezone.utc)
    created_at = (now - timedelta(hours=10)).isoformat()

    cursor = conn.cursor()
    cursor.execute(
        "INSERT INTO nodes (type, label, properties, created_at) VALUES (?, ?, ?, ?)",
        ("milestone", "Core Engine API", '{"owner": "Bob", "deadline_hours": 2, "status": "in_progress"}', created_at),
    )
    m_id = cursor.lastrowid
    conn.commit()
    conn.close()

    # First run: should create risk node and edge
    result1 = runner.invoke(app, ["status"])
    assert result1.exit_code == 0
    assert "AT RISK" in result1.output
    assert "Overdue: Core Engine API" in result1.output

    conn = sqlite3.connect(db_path)
    all_risks = find_nodes(conn, type="risk")
    overdue_risks1 = [r for r in all_risks if r["properties"].get("signal") == "milestone_overdue"]
    assert len(overdue_risks1) == 1
    assert overdue_risks1[0]["properties"]["milestone_id"] == m_id

    edges1 = get_edges_from(conn, m_id, relation="causes")
    assert len(edges1) == 1
    assert edges1[0]["target_id"] == overdue_risks1[0]["id"]
    conn.close()

    # Second run: should NOT create duplicate overdue risk node
    result2 = runner.invoke(app, ["status"])
    assert result2.exit_code == 0

    conn = sqlite3.connect(db_path)
    all_risks2 = find_nodes(conn, type="risk")
    overdue_risks2 = [r for r in all_risks2 if r["properties"].get("signal") == "milestone_overdue"]
    assert len(overdue_risks2) == 1
    conn.close()


def test_status_commit_silence_heartbeat(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    arc_dir = tmp_path / ".arc"
    arc_dir.mkdir()
    db_path = arc_dir / "arc.db"

    conn = sqlite3.connect(db_path)
    init_graph_schema(conn)

    now = datetime.now(timezone.utc)
    created_at = (now - timedelta(minutes=30)).isoformat()

    # Upcoming deadline in 1 hour (less than 2 hours remaining)
    cursor = conn.cursor()
    cursor.execute(
        "INSERT INTO nodes (type, label, properties, created_at) VALUES (?, ?, ?, ?)",
        ("milestone", "Deployment Script", '{"owner": "Charlie", "deadline_hours": 1, "status": "not_started"}', created_at),
    )
    conn.commit()
    conn.close()

    # Run with silence-hours 0.1 (no commits in last 0.1 hrs)
    result = runner.invoke(app, ["status", "--silence-hours", "0.1"])
    assert result.exit_code == 0
    assert "Commit Silence Warning" in result.output
    assert "commit_silence" in result.output
