import sqlite3
from pathlib import Path
from typer.testing import CliRunner

from arc_cli.main import app
from arc_cli.graph import (
    add_node,
    find_nodes,
    init_graph_schema,
)

runner = CliRunner()


def test_report_command_creates_file_and_memory_node(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)

    # Initialize arc db
    result_init = runner.invoke(app, ["init"])
    assert result_init.exit_code == 0

    arc_db = tmp_path / ".arc" / "arc.db"
    conn = sqlite3.connect(arc_db)
    init_graph_schema(conn)

    m1 = add_node(
        conn,
        type="milestone",
        label="Core Graph Engine",
        properties={"owner": "Alice", "deadline_hours": 12, "status": "completed"},
    )
    r1 = add_node(
        conn,
        type="risk",
        label="Commit Silence Warning",
        properties={"signal": "commit_silence", "severity": "medium", "resolved": False},
    )
    d1 = add_node(
        conn,
        type="decision",
        label="Decision for Risk #2: STAY SILENT",
        properties={"risk_id": r1, "final_verdict": False, "combined_reasoning": "Timing anti-spam limit reached"},
    )
    conn.commit()
    conn.close()

    result_report = runner.invoke(app, ["report"])
    assert result_report.exit_code == 0
    assert "Report saved to:" in result_report.output

    report_file = tmp_path / ".arc" / "report.md"
    assert report_file.exists()
    content = report_file.read_text(encoding="utf-8")
    assert "Pitch-Readiness Summary" in content or "Report" in content
    assert len(content) > 50

    # Verify latest_report_context memory node
    conn = sqlite3.connect(arc_db)
    mem_nodes = find_nodes(conn, type="memory", label="latest_report_context")
    assert len(mem_nodes) == 1
    assert "Core Graph Engine" in mem_nodes[0]["properties"]["content"]
    conn.close()
