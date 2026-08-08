from datetime import datetime, timezone
from pathlib import Path
import sqlite3
from typing import List, Optional
from dotenv import load_dotenv
from rich.console import Console
from rich.table import Table
import typer

from arc_cli.graph import (
    add_edge,
    add_node,
    find_nodes,
    get_latest_context,
    init_graph_schema,
    update_node_properties,
)
from arc_cli.llm import generate_plan_response, parse_plan_json

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


@app.command()
def plan(
    model: Optional[str] = typer.Option(
        None, "--model", "-m", help="Override local LLM model name/path"
    )
):
    """Generate project plan milestones from ingested context using local LLM."""
    load_dotenv()

    arc_dir = Path(".arc")
    db_path = arc_dir / "arc.db"

    conn = sqlite3.connect(db_path)
    try:
        init_graph_schema(conn)
        context = get_latest_context(conn)
        if not context or not context.strip():
            typer.echo("Error: No ingested context found. Please run 'arc ingest' first.", err=True)
            raise typer.Exit(code=1)

        typer.echo("Generating project plan from ingested context using local LLM...")
        try:
            raw_response = generate_plan_response(context, model_name=model)
            milestones = parse_plan_json(raw_response)
        except Exception as e:
            typer.echo(f"Error generating or parsing plan: {e}", err=True)
            raise typer.Exit(code=1)

        if not milestones:
            typer.echo("No milestones returned by LLM.")
            return

        name_to_id = {}
        for m in milestones:
            name = str(m.get("name", "Unnamed Milestone"))
            owner = str(m.get("owner", "unassigned"))
            try:
                deadline_hours = int(float(m.get("deadline_hours", 0)))
            except (ValueError, TypeError):
                deadline_hours = 0

            node_id = add_node(
                conn,
                type="milestone",
                label=name,
                properties={
                    "owner": owner,
                    "deadline_hours": deadline_hours,
                    "status": "not_started",
                },
            )
            name_to_id[name] = node_id

        for m in milestones:
            name = str(m.get("name", "Unnamed Milestone"))
            if name in name_to_id:
                current_id = name_to_id[name]
                depends_on_list = m.get("depends_on", [])
                if isinstance(depends_on_list, list):
                    for dep_name in depends_on_list:
                        dep_name_str = str(dep_name)
                        if dep_name_str in name_to_id:
                            dep_id = name_to_id[dep_name_str]
                            add_edge(conn, source_id=current_id, target_id=dep_id, relation="depends_on")

        console = Console()
        table = Table(title="ARC Project Plan Milestones")
        table.add_column("Node ID", justify="right", style="cyan", no_wrap=True)
        table.add_column("Milestone Name", style="bold white")
        table.add_column("Owner", style="magenta")
        table.add_column("Deadline (hrs)", justify="right", style="green")
        table.add_column("Depends On", style="yellow")

        for m in milestones:
            name = str(m.get("name", "Unnamed Milestone"))
            node_id = name_to_id[name]
            owner = str(m.get("owner", "unassigned"))
            try:
                deadline = str(int(float(m.get("deadline_hours", 0))))
            except (ValueError, TypeError):
                deadline = "0"
            deps = m.get("depends_on", [])
            dep_str = ", ".join(deps) if isinstance(deps, list) and deps else "None"
            table.add_row(str(node_id), name, owner, deadline, dep_str)

        console.print(table)
    finally:
        conn.close()


if __name__ == "__main__":
    app()


