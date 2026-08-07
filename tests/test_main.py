from pathlib import Path
from typer.testing import CliRunner
from arc_cli.main import app

runner = CliRunner()


def test_cli_init(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    result = runner.invoke(app, ["init"])
    assert result.exit_code == 0
    assert "Project initialized." in result.output
    assert (tmp_path / ".arc" / "arc.db").exists()

    # Test idempotency (run again)
    result_second = runner.invoke(app, ["init"])
    assert result_second.exit_code == 0
    assert "Project initialized." in result_second.output


def test_cli_ingest(tmp_path, monkeypatch):
    import sqlite3
    from arc_cli.graph import get_latest_context

    monkeypatch.chdir(tmp_path)
    f1 = tmp_path / "README.md"
    f1.write_text("This is the README", encoding="utf-8")
    f2 = tmp_path / "problem_statement.md"
    f2.write_text("This is the problem statement", encoding="utf-8")

    result = runner.invoke(app, ["ingest", str(f1), str(f2)])
    assert result.exit_code == 0
    assert "Ingested 2 file(s)" in result.output

    db_conn = sqlite3.connect(tmp_path / ".arc" / "arc.db")
    ctx = get_latest_context(db_conn)
    db_conn.close()

    assert "--- FILE: " in ctx
    assert "This is the README" in ctx
    assert "This is the problem statement" in ctx

    # Test re-ingest (overwrite, not duplicate node)
    f1.write_text("Updated README content", encoding="utf-8")
    result_reingest = runner.invoke(app, ["ingest", str(f1)])
    assert result_reingest.exit_code == 0
    assert "Ingested 1 file(s)" in result_reingest.output

    db_conn = sqlite3.connect(tmp_path / ".arc" / "arc.db")
    ctx_updated = get_latest_context(db_conn)
    cursor = db_conn.cursor()
    cursor.execute("SELECT COUNT(*) FROM nodes WHERE type='memory' AND label='ingested_context'")
    count = cursor.fetchone()[0]
    db_conn.close()

    assert count == 1
    assert "Updated README content" in ctx_updated
    assert "This is the problem statement" not in ctx_updated

