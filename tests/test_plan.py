import sqlite3, json
from unittest.mock import patch
import pytest
from typer.testing import CliRunner

from arc_cli.main import app
from arc_cli.llm import parse_plan_json
from arc_cli.graph import find_nodes, get_edges_from

runner = CliRunner()


def test_parse_plan_json_plain():
    raw = '{"milestones": [{"name": "M1", "owner": "Alice", "deadline_hours": 10, "depends_on": []}]}'
    result = parse_plan_json(raw)
    assert len(result) == 1
    assert result[0]["name"] == "M1"
    assert result[0]["owner"] == "Alice"


def test_parse_plan_json_with_code_fences():
    raw = """
Here is the generated plan:
```json
{
  "milestones": [
    {"name": "M1", "owner": "Alice", "deadline_hours": 5, "depends_on": []},
    {"name": "M2", "owner": "Bob", "deadline_hours": 10, "depends_on": ["M1"]}
  ]
}
```
Hope this helps!
"""
    result = parse_plan_json(raw)
    assert len(result) == 2
    assert result[0]["name"] == "M1"
    assert result[1]["depends_on"] == ["M1"]


def test_parse_plan_json_invalid():
    with pytest.raises(ValueError):
        parse_plan_json("This is not JSON at all!")

    with pytest.raises(ValueError):
        parse_plan_json('{"other": 123}')


def test_arc_plan_empty_context(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    runner.invoke(app, ["init"])

    result = runner.invoke(app, ["plan"])
    assert result.exit_code == 1
    assert "No ingested context found" in result.output


def test_arc_plan_success(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    readme = tmp_path / "README.md"
    readme.write_text("Build knowledge graph CLI app.", encoding="utf-8")

    runner.invoke(app, ["ingest", str(readme)])

    fake_response = """
```json
{
  "milestones": [
    {"name": "Init Project", "owner": "Dev A", "deadline_hours": 2, "depends_on": []},
    {"name": "Graph Engine", "owner": "Dev B", "deadline_hours": 8, "depends_on": ["Init Project"]}
  ]
}
```
"""
    with patch("arc_cli.main.generate_plan_response", return_value=fake_response) as mock_llm:
        result = runner.invoke(app, ["plan"])
        assert result.exit_code == 0
        assert mock_llm.called
        assert "Init Project" in result.output
        assert "Graph Engine" in result.output
        assert "Dev A" in result.output

    # Check database nodes and edges
    db_path = tmp_path / ".arc" / "arc.db"
    conn = sqlite3.connect(db_path)
    nodes = find_nodes(conn, type="milestone")
    assert len(nodes) == 2

    node_map = {n["label"]: n for n in nodes}
    assert "Init Project" in node_map
    assert "Graph Engine" in node_map

    init_node = node_map["Init Project"]
    engine_node = node_map["Graph Engine"]

    assert init_node["properties"]["owner"] == "Dev A"
    assert init_node["properties"]["deadline_hours"] == 2
    assert init_node["properties"]["status"] == "not_started"

    # Check edge: Graph Engine depends on Init Project (source=Engine, target=Init)
    edges = get_edges_from(conn, engine_node["id"], relation="depends_on")
    assert len(edges) == 1
    assert edges[0]["target_id"] == init_node["id"]

    conn.close()


def test_arc_plan_llm_json_error(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    readme = tmp_path / "README.md"
    readme.write_text("Context text", encoding="utf-8")
    runner.invoke(app, ["ingest", str(readme)])

    with patch("arc_cli.main.generate_plan_response", return_value="Failed response"):
        result = runner.invoke(app, ["plan"])
        assert result.exit_code == 1
        assert "Error generating or parsing plan" in result.output
