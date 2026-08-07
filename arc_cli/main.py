from pathlib import Path
import sqlite3
import typer

from arc_cli.graph import init_graph_schema

app = typer.Typer()


@app.callback()
def main_callback():
    """ARC CLI - Knowledge Graph CLI for hackathons and projects."""
    pass


@app.command()
def init():
    arc_dir = Path(".arc")
    arc_dir.mkdir(parents=True, exist_ok=True)

    db_path = arc_dir / "arc.db"
    conn = sqlite3.connect(db_path)
    try:
        init_graph_schema(conn)
    finally:
        conn.close()

    typer.echo("Project initialized.")


if __name__ == "__main__":
    app()
