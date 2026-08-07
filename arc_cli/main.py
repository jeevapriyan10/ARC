from datetime import datetime, timezone
from pathlib import Path
import sqlite3
from typing import List
import typer

from arc_cli.graph import (
    add_node,
    find_nodes,
    init_graph_schema,
    update_node_properties,
)

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


@app.command()
def ingest(
    files: List[Path] = typer.Argument(
        ..., help="One or more file paths to ingest (e.g. problem_statement.md, README.md)"
    )
):
    """Ingest problem statements, READMEs, or documentation into graph memory."""
    arc_dir = Path(".arc")
    arc_dir.mkdir(parents=True, exist_ok=True)
    db_path = arc_dir / "arc.db"

    conn = sqlite3.connect(db_path)
    try:
        init_graph_schema(conn)

        file_sections = []
        source_filenames = []

        for file_path in files:
            if not file_path.exists():
                typer.echo(f"Error: File '{file_path}' does not exist.", err=True)
                raise typer.Exit(code=1)

            try:
                content = file_path.read_text(encoding="utf-8")
            except Exception as e:
                typer.echo(f"Error reading file '{file_path}': {e}", err=True)
                raise typer.Exit(code=1)

            source_filenames.append(str(file_path))
            file_sections.append(f"--- FILE: {file_path} ---\n{content}")

        concatenated_context = "\n\n".join(file_sections)
        timestamp = datetime.now(timezone.utc).isoformat()
        properties = {
            "content": concatenated_context,
            "source_files": source_filenames,
            "ingested_at": timestamp,
        }

        existing_nodes = find_nodes(conn, type="memory", label="ingested_context")
        if existing_nodes:
            node_id = existing_nodes[0]["id"]
            update_node_properties(conn, node_id, properties)
        else:
            add_node(conn, type="memory", label="ingested_context", properties=properties)

        char_count = len(concatenated_context)
        file_count = len(source_filenames)
        typer.echo(f"Ingested {file_count} file(s) ({char_count} total characters).")
    finally:
        conn.close()


if __name__ == "__main__":
    app()

