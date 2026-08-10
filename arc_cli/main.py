import re
import subprocess
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
    get_edges_from,
    get_latest_context,
    get_node,
    init_graph_schema,
    update_node_properties,
)
from arc_cli.gate import run_gate
from arc_cli.llm import generate_plan_response, generate_report_response, parse_plan_json

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


@app.command()
def watch():
    """Install git post-commit hook to automatically track commits in ARC graph."""
    git_dir = Path(".git")
    if not git_dir.exists():
        typer.echo("Error: Not a git repository (.git directory not found).", err=True)
        raise typer.Exit(code=1)

    hooks_dir = git_dir / "hooks"
    hooks_dir.mkdir(parents=True, exist_ok=True)

    hook_file = hooks_dir / "post-commit"
    if hook_file.exists():
        typer.echo("Warning: .git/hooks/post-commit already exists. Skipping installation.", err=True)
        return

    hook_content = "#!/bin/sh\npython -m arc_cli.main on-commit\n"
    hook_file.write_text(hook_content, encoding="utf-8")
    try:
        hook_file.chmod(0o755)
    except Exception:
        pass

    typer.echo("Git post-commit hook installed successfully.")


@app.command(hidden=True)
def on_commit():
    """Internal hook executed by git post-commit to record commits in ARC graph."""
    arc_dir = Path(".arc")
    db_path = arc_dir / "arc.db"
    if not db_path.exists():
        return

    try:
        commit_hash = subprocess.check_output(
            ["git", "rev-parse", "HEAD"], text=True
        ).strip()
    except Exception:
        return

    try:
        raw_files = subprocess.check_output(
            ["git", "diff-tree", "--no-commit-id", "--name-only", "-r", "HEAD"],
            text=True,
        ).strip()
        changed_files = [f.strip() for f in raw_files.splitlines() if f.strip()]
    except Exception:
        changed_files = []

    timestamp = datetime.now(timezone.utc).isoformat()

    conn = sqlite3.connect(db_path)
    try:
        init_graph_schema(conn)

        commit_label = f"Commit {commit_hash[:7]}"
        commit_props = {
            "hash": commit_hash,
            "timestamp": timestamp,
            "files": changed_files,
        }
        commit_node_id = add_node(conn, type="commit", label=commit_label, properties=commit_props)

        milestones = find_nodes(conn, type="milestone")
        linked_milestones = []

        for m in milestones:
            m_id = m["id"]
            m_label = m["label"]
            m_props = m.get("properties", {})

            # Naive heuristic: check if milestone label or significant keywords are substring matched in changed file paths
            keywords = [w.lower() for w in re.split(r"\W+", m_label) if len(w) > 2]
            
            matched = False
            for fpath in changed_files:
                fpath_lower = fpath.lower()
                if m_label.lower() in fpath_lower or any(kw in fpath_lower for kw in keywords):
                    matched = True
                    break

            if matched:
                add_edge(conn, source_id=commit_node_id, target_id=m_id, relation="touches")
                if m_props.get("status") == "not_started":
                    m_props["status"] = "in_progress"
                    update_node_properties(conn, m_id, m_props)
                linked_milestones.append(m_label)

        if linked_milestones:
            m_str = ", ".join(linked_milestones)
            typer.echo(f"Commit {commit_hash[:7]} linked to milestone(s): {m_str}")
        else:
            typer.echo(f"Commit {commit_hash[:7]} recorded (no milestone match).")
    finally:
        conn.close()


@app.command()
def status(
    silence_hours: float = typer.Option(
        3.0, "--silence-hours", "-s", help="Commit silence threshold in hours for heartbeat detection"
    )
):
    """Show project status, milestone deadlines, elapsed time, and active risks."""
    arc_dir = Path(".arc")
    db_path = arc_dir / "arc.db"
    if not db_path.exists():
        typer.echo("Error: Database not found. Please run 'arc init' first.", err=True)
        raise typer.Exit(code=1)

    conn = sqlite3.connect(db_path)
    try:
        init_graph_schema(conn)

        now = datetime.now(timezone.utc)
        milestones = find_nodes(conn, type="milestone")
        commits = find_nodes(conn, type="commit")

        if not milestones:
            typer.echo("No milestones found in graph. Run 'arc plan' first.")
            return

        at_risk_count = 0

        for m in milestones:
            m_id = m["id"]
            m_label = m["label"]
            m_props = m.get("properties", {})
            created_at_str = m.get("created_at")

            try:
                created_dt = datetime.fromisoformat(created_at_str)
                if created_dt.tzinfo is None:
                    created_dt = created_dt.replace(tzinfo=timezone.utc)
                elapsed_seconds = (now - created_dt).total_seconds()
                elapsed_hours = elapsed_seconds / 3600.0
            except Exception:
                elapsed_hours = 0.0

            deadline_hours = float(m_props.get("deadline_hours", 0))
            current_status = m_props.get("status", "not_started")

            is_overdue = (elapsed_hours > deadline_hours) and (current_status in ["not_started", "in_progress"])
            m["elapsed_hours"] = elapsed_hours
            m["is_overdue"] = is_overdue

            if is_overdue:
                at_risk_count += 1
                # Edge direction choice: milestone -> risk (relation='causes')
                # A milestone exceeding its deadline causes a risk node to be generated.
                existing_causes = get_edges_from(conn, m_id, relation="causes")
                risk_already_exists = False
                for edge in existing_causes:
                    target_node = get_node(conn, edge["target_id"])
                    if target_node and target_node.get("type") == "risk":
                        risk_already_exists = True
                        break

                if not risk_already_exists:
                    risk_props = {
                        "signal": "milestone_overdue",
                        "severity": "high",
                        "resolved": False,
                        "milestone_id": m_id,
                    }
                    risk_label = f"Overdue: {m_label}"
                    risk_id = add_node(conn, type="risk", label=risk_label, properties=risk_props)
                    add_edge(conn, source_id=m_id, target_id=risk_id, relation="causes")

        # Heartbeat check: commits in last N hours
        last_commit_hours = None
        if commits:
            commit_times = []
            for c in commits:
                c_time_str = c.get("created_at") or c.get("properties", {}).get("timestamp")
                if c_time_str:
                    try:
                        cdt = datetime.fromisoformat(c_time_str)
                        if cdt.tzinfo is None:
                            cdt = cdt.replace(tzinfo=timezone.utc)
                        commit_times.append(cdt)
                    except Exception:
                        pass
            if commit_times:
                most_recent_commit = max(commit_times)
                last_commit_hours = (now - most_recent_commit).total_seconds() / 3600.0

        commit_silence = (last_commit_hours is None or last_commit_hours > silence_hours)

        has_urgent_milestone = False
        for m in milestones:
            m_props = m.get("properties", {})
            st = m_props.get("status", "not_started")
            dl = float(m_props.get("deadline_hours", 0))
            el = m.get("elapsed_hours", 0.0)
            remaining_hours = dl - el
            if st in ["not_started", "in_progress"] and (remaining_hours <= 2.0 or el > dl):
                has_urgent_milestone = True
                break

        if commit_silence and has_urgent_milestone:
            existing_risks = find_nodes(conn, type="risk")
            silence_risk_exists = False
            for r in existing_risks:
                r_props = r.get("properties", {})
                if r_props.get("signal") == "commit_silence" and not r_props.get("resolved", False):
                    silence_risk_exists = True
                    break

            if not silence_risk_exists:
                silence_props = {
                    "signal": "commit_silence",
                    "severity": "medium",
                    "resolved": False,
                    "silence_hours": silence_hours,
                }
                add_node(conn, type="risk", label="Commit Silence Warning", properties=silence_props)

        active_risks = [
            r for r in find_nodes(conn, type="risk")
            if not r.get("properties", {}).get("resolved", False)
        ]

        console = Console()
        m_table = Table(title="ARC Milestone Status & Drift Detection")
        m_table.add_column("ID", justify="right", style="cyan", no_wrap=True)
        m_table.add_column("Milestone Name", style="bold white", no_wrap=True)
        m_table.add_column("Owner", style="magenta")
        m_table.add_column("Status", style="yellow")
        m_table.add_column("Elapsed (hrs)", justify="right", style="blue")
        m_table.add_column("Deadline (hrs)", justify="right", style="green")
        m_table.add_column("Risk Flag", style="bold red")

        for m in milestones:
            m_id = str(m["id"])
            name = m["label"]
            owner = str(m.get("properties", {}).get("owner", "unassigned"))
            st = str(m.get("properties", {}).get("status", "not_started"))
            el = f"{m.get('elapsed_hours', 0.0):.1f}"
            dl = str(m.get("properties", {}).get("deadline_hours", 0))
            risk_flag = "[bold red]AT RISK[/bold red]" if m.get("is_overdue") else "[green]OK[/green]"
            m_table.add_row(m_id, name, owner, st, el, dl, risk_flag)

        console.print(m_table)

        if active_risks:
            r_table = Table(title="Active Risks & Drift Warnings")
            r_table.add_column("Risk ID", justify="right", style="cyan")
            r_table.add_column("Signal", style="bold yellow")
            r_table.add_column("Severity", style="bold red")
            r_table.add_column("Description", style="white")

            for r in active_risks:
                rid = str(r["id"])
                sig = str(r.get("properties", {}).get("signal", "unknown"))
                sev = str(r.get("properties", {}).get("severity", "medium")).upper()
                desc = r["label"]
                r_table.add_row(rid, sig, sev, desc)

            console.print(r_table)

            g_table = Table(title="ARC Intervention Gate Decisions")
            g_table.add_column("Risk ID", justify="right", style="cyan")
            g_table.add_column("Verdict", style="bold")
            g_table.add_column("Materiality", style="green")
            g_table.add_column("Timing", style="yellow")
            g_table.add_column("Specificity", style="blue")
            g_table.add_column("Reasoning", style="white")

            for r in active_risks:
                decision = run_gate(conn, r["id"])
                verdict_styled = (
                    "[bold green]FIRE NUDGE[/bold green]"
                    if decision["final_verdict"]
                    else "[bold red]STAY SILENT[/bold red]"
                )
                mat_str = "[green]PASS[/green]" if decision["materiality_result"] else "[red]FAIL[/red]"
                tim_str = "[green]PASS[/green]" if decision["timing_result"] else "[red]FAIL[/red]"
                spec_str = "[green]PASS[/green]" if decision["specificity_result"] else "[red]FAIL[/red]"

                g_table.add_row(
                    str(r["id"]),
                    verdict_styled,
                    mat_str,
                    tim_str,
                    spec_str,
                    decision["combined_reasoning"],
                )

            console.print(g_table)
        else:
            console.print("[green]No active risks detected.[/green]")
    finally:
        conn.close()


@app.command()
def report(
    model: Optional[str] = typer.Option(
        None, "--model", "-m", help="Override local LLM model name/path"
    )
):
    """Generate pitch readiness summary, blocker digest, and pitch outline."""
    arc_dir = Path(".arc")
    arc_dir.mkdir(parents=True, exist_ok=True)
    db_path = arc_dir / "arc.db"

    if not db_path.exists():
        typer.echo("Error: Database not found. Please run 'arc init' first.", err=True)
        raise typer.Exit(code=1)

    conn = sqlite3.connect(db_path)
    try:
        init_graph_schema(conn)

        milestones = find_nodes(conn, type="milestone")
        commits = find_nodes(conn, type="commit")
        decision_nodes = find_nodes(conn, type="decision")
        nudge_nodes = find_nodes(conn, type="nudge")
        unresolved_risks = [
            r for r in find_nodes(conn, type="risk")
            if not r.get("properties", {}).get("resolved", False)
        ]
        ingested_context = get_latest_context(conn)

        # Build context summary string
        context_lines = ["=== ARC PROJECT GRAPH REPORT CONTEXT ==="]
        if ingested_context:
            context_lines.append(f"\n--- INGESTED PROJECT CONTEXT ---\n{ingested_context}")

        context_lines.append("\n--- MILESTONES ---")
        if milestones:
            for m in milestones:
                props = m.get("properties", {})
                st = props.get("status", "not_started")
                owner = props.get("owner", "unassigned")
                deadline = props.get("deadline_hours", 0)
                context_lines.append(f"- ID #{m['id']} '{m['label']}' | Status: {st} | Owner: {owner} | Deadline: {deadline}h")
        else:
            context_lines.append("- None")

        context_lines.append("\n--- UNRESOLVED RISKS ---")
        if unresolved_risks:
            for r in unresolved_risks:
                props = r.get("properties", {})
                sig = props.get("signal", "unknown")
                sev = props.get("severity", "medium")
                context_lines.append(f"- Risk #{r['id']} '{r['label']}' | Signal: {sig} | Severity: {sev}")
        else:
            context_lines.append("- None")

        context_lines.append("\n--- INTERVENTION GATE DECISIONS ---")
        if decision_nodes:
            for d in decision_nodes:
                props = d.get("properties", {})
                verdict = "FIRE NUDGE" if props.get("final_verdict") else "STAY SILENT"
                reason = props.get("combined_reasoning", "")
                context_lines.append(f"- Decision #{d['id']} for Risk #{props.get('risk_id')} | Verdict: {verdict} | Reasoning: {reason}")
        else:
            context_lines.append("- None")

        context_lines.append("\n--- RECENT NUDGES ---")
        if nudge_nodes:
            for n in nudge_nodes:
                props = n.get("properties", {})
                msg = props.get("message", "")
                ts = props.get("timestamp", "")
                context_lines.append(f"- Nudge #{n['id']} at {ts} | Message: {msg}")
        else:
            context_lines.append("- None")

        context_lines.append("\n--- RECENT COMMITS ---")
        if commits:
            for c in commits[-5:]:
                props = c.get("properties", {})
                files = ", ".join(props.get("files", []))
                context_lines.append(f"- {c['label']} at {props.get('timestamp', '')} | Files: {files}")
        else:
            context_lines.append("- None")

        report_context = "\n".join(context_lines)

        # Store as 'memory' node (label='latest_report_context') in graph
        timestamp = datetime.now(timezone.utc).isoformat()
        report_mem_props = {
            "content": report_context,
            "generated_at": timestamp,
        }
        existing_mems = find_nodes(conn, type="memory", label="latest_report_context")
        if existing_mems:
            update_node_properties(conn, existing_mems[0]["id"], report_mem_props)
        else:
            add_node(conn, type="memory", label="latest_report_context", properties=report_mem_props)

        typer.echo("Generating project report and pitch readiness summary using local LLM...")
        report_markdown = generate_report_response(report_context, model_name=model)

        report_file = arc_dir / "report.md"
        report_file.write_text(report_markdown, encoding="utf-8")

        from rich.markdown import Markdown
        console = Console()
        console.print("\n", Markdown(report_markdown))
        typer.echo(f"\nReport saved to: {report_file}")
    finally:
        conn.close()


if __name__ == "__main__":
    app()




