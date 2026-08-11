import json
import sqlite3
from pathlib import Path
from typer.testing import CliRunner

from arc_cli.graph import (
    BASE_DEMO_TIME,
    add_node,
    get_current_time,
    get_project_clock,
    init_graph_schema,
    set_project_clock,
)
from arc_cli.main import app

runner = CliRunner()


def test_project_clock_helpers(tmp_path: Path):
    db_path = tmp_path / "test_clock.db"
    conn = sqlite3.connect(db_path)
    try:
        init_graph_schema(conn)

        # Initial clock should be None
        assert get_project_clock(conn) is None

        # Set fake clock to hour 6
        set_project_clock(conn, 6.0)
        assert get_project_clock(conn) == 6.0

        current_time = get_current_time(conn)
        expected_iso = "2026-01-01T06:00:00+00:00"
        assert current_time.isoformat() == expected_iso

        # Advance fake clock to hour 11
        set_project_clock(conn, 11.5)
        assert get_project_clock(conn) == 11.5

        # Node created without timestamp should default to project clock
        node_id = add_node(conn, type="milestone", label="Demo Milestone")
        cursor = conn.cursor()
        cursor.execute("SELECT created_at FROM nodes WHERE id = ?", (node_id,))
        row = cursor.fetchone()
        assert row[0] == "2026-01-01T11:30:00+00:00"
    finally:
        conn.close()


def test_arc_demo_command(tmp_path: Path):
    script_file = tmp_path / "demo_script.json"
    demo_data = [
        {
            "type": "setup",
            "hour": 0,
            "milestones": [
                {
                    "name": "Auth Login API",
                    "owner": "Alice",
                    "deadline_hours": 8,
                    "status": "not_started"
                },
                {
                    "name": "User Dashboard UI",
                    "owner": "Bob",
                    "deadline_hours": 16,
                    "status": "not_started",
                    "depends_on": ["Auth Login API"]
                }
            ]
        },
        {"type": "commit", "hour": 6, "files": ["auth/login.py"]},
        {"type": "advance_time", "hour": 10},
        {"type": "commit", "hour": 11, "files": ["auth/login.py"]},
        {"type": "advance_time", "hour": 20}
    ]
    script_file.write_text(json.dumps(demo_data), encoding="utf-8")
    db_file = tmp_path / "demo.db"

    result = runner.invoke(app, ["demo", str(script_file), "--delay", "0", "--db", str(db_file)])

    assert result.exit_code == 0
    assert "ARC Scripted Demo Timeline Replay" in result.output
    assert "Step 1/5: Project Hour 0.0" in result.output
    assert "Step 2/5: Project Hour 6.0" in result.output
    assert "Step 3/5: Project Hour 10.0" in result.output
    assert "Step 4/5: Project Hour 11.0" in result.output
    assert "Step 5/5: Project Hour 20.0" in result.output
    assert "Demo Replay Finished" in result.output
