import sqlite3
from unittest.mock import patch
from typer.testing import CliRunner

from arc_cli.main import app
from arc_cli.graph import (
    init_graph_schema,
    add_node,
    get_node,
    get_edges_from,
    find_nodes,
)

runner = CliRunner()


def test_watch_not_git_repo(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    result = runner.invoke(app, ["watch"])
    assert result.exit_code == 1
    assert "Not a git repository" in result.output


def test_watch_install_and_idempotence(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    git_dir = tmp_path / ".git"
    git_dir.mkdir()

    result = runner.invoke(app, ["watch"])
    assert result.exit_code == 0
    assert "Git post-commit hook installed successfully." in result.output

    hook_file = git_dir / "hooks" / "post-commit"
    assert hook_file.exists()
    assert "python -m arc_cli.main on-commit" in hook_file.read_text()

    # Second run should warn and skip
    result_dup = runner.invoke(app, ["watch"])
    assert result_dup.exit_code == 0
    assert "already exists. Skipping installation." in result_dup.output


def test_on_commit_with_milestone_match(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    arc_dir = tmp_path / ".arc"
    arc_dir.mkdir()
    db_path = arc_dir / "arc.db"

    conn = sqlite3.connect(db_path)
    init_graph_schema(conn)
    m_id = add_node(
        conn,
        type="milestone",
        label="ARC CLI Development",
        properties={"owner": "Alice", "deadline_hours": 10, "status": "not_started"},
    )
    conn.close()

    def mock_subprocess(cmd, text=True):
        if "rev-parse" in cmd:
            return "1234567890abcdef"
        if "diff-tree" in cmd:
            return "arc_cli/main.py\nREADME.md\n"
        return ""

    with patch("subprocess.check_output", side_effect=mock_subprocess):
        result = runner.invoke(app, ["on-commit"])
        assert result.exit_code == 0
        assert "Commit 1234567 linked to milestone(s): ARC CLI Development" in result.output

    conn = sqlite3.connect(db_path)
    commit_nodes = find_nodes(conn, type="commit")
    assert len(commit_nodes) == 1
    c_node = commit_nodes[0]
    assert c_node["label"] == "Commit 1234567"
    assert c_node["properties"]["hash"] == "1234567890abcdef"
    assert "arc_cli/main.py" in c_node["properties"]["files"]

    # Check touches edge
    edges = get_edges_from(conn, c_node["id"], relation="touches")
    assert len(edges) == 1
    assert edges[0]["target_id"] == m_id

    # Check milestone status flipped to in_progress
    updated_m = get_node(conn, m_id)
    assert updated_m["properties"]["status"] == "in_progress"
    conn.close()


def test_on_commit_no_match(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    arc_dir = tmp_path / ".arc"
    arc_dir.mkdir()
    db_path = arc_dir / "arc.db"

    conn = sqlite3.connect(db_path)
    init_graph_schema(conn)
    add_node(
        conn,
        type="milestone",
        label="Frontend UI",
        properties={"owner": "Bob", "deadline_hours": 5, "status": "not_started"},
    )
    conn.close()

    def mock_subprocess(cmd, text=True):
        if "rev-parse" in cmd:
            return "abcdef1234567890"
        if "diff-tree" in cmd:
            return "backend/server.py\n"
        return ""

    with patch("subprocess.check_output", side_effect=mock_subprocess):
        result = runner.invoke(app, ["on-commit"])
        assert result.exit_code == 0
        assert "Commit abcdef1 recorded (no milestone match)." in result.output

    conn = sqlite3.connect(db_path)
    commit_nodes = find_nodes(conn, type="commit")
    assert len(commit_nodes) == 1
    c_node = commit_nodes[0]

    edges = get_edges_from(conn, c_node["id"], relation="touches")
    assert len(edges) == 0
    conn.close()
