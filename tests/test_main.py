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
