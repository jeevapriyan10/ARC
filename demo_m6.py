"""
Module 6 Intervention Gate Demo Script.

Demonstrates:
1. Fire Nudge (Materiality pass, Timing pass, Specificity pass)
2. Stay Silent due to Materiality (0 dependents + deadline not passed)
3. Stay Silent due to Timing (anti-spam window blocks repeat nudge)
4. Decision node persistence and graph query count
5. Rich side-by-side decision comparison for presentation/pitch
"""

from datetime import datetime, timedelta, timezone
from pathlib import Path
import sqlite3

from rich.console import Console
from rich.table import Table
from rich.panel import Panel

from arc_cli.graph import (
    add_edge,
    add_node,
    find_nodes,
    init_graph_schema,
)
from arc_cli.gate import run_gate


def main():
    db_path = Path("demo_m6.db")
    if db_path.exists():
        db_path.unlink()

    conn = sqlite3.connect(db_path)
    init_graph_schema(conn)

    now = datetime.now(timezone.utc)
    past_10h = (now - timedelta(hours=10)).isoformat()
    recent_1h = (now - timedelta(hours=1)).isoformat()

    console = Console()
    console.print(Panel.fit("[bold cyan]ARC Intervention Gate - Core Logic Demo[/bold cyan]"))

    # --- Setup Milestone 1 & Risk 1 (Target: FIRE NUDGE) ---
    m1_id = add_node(
        conn,
        type="milestone",
        label="Core Engine API",
        properties={"owner": "Alice", "deadline_hours": 2, "status": "in_progress"},
    )
    conn.cursor().execute("UPDATE nodes SET created_at = ? WHERE id = ?", (past_10h, m1_id))

    m2_id = add_node(
        conn,
        type="milestone",
        label="Mobile Client Integration",
        properties={"owner": "Bob", "deadline_hours": 24, "status": "not_started"},
    )
    add_edge(conn, source_id=m2_id, target_id=m1_id, relation="depends_on")

    r1_id = add_node(
        conn,
        type="risk",
        label="Overdue: Core Engine API",
        properties={"signal": "milestone_overdue", "severity": "high", "milestone_id": m1_id, "resolved": False},
    )
    add_edge(conn, source_id=m1_id, target_id=r1_id, relation="causes")

    # --- Setup Milestone 3 & Risk 2 (Target: STAY SILENT - Materiality Fail) ---
    m3_id = add_node(
        conn,
        type="milestone",
        label="Optional Documentation Polish",
        properties={"owner": "Charlie", "deadline_hours": 48, "status": "not_started"},
    )
    conn.cursor().execute("UPDATE nodes SET created_at = ? WHERE id = ?", (recent_1h, m3_id))

    r2_id = add_node(
        conn,
        type="risk",
        label="Warning: Optional Documentation Polish",
        properties={"signal": "milestone_overdue", "severity": "low", "milestone_id": m3_id, "resolved": False},
    )
    add_edge(conn, source_id=m3_id, target_id=r2_id, relation="causes")

    conn.commit()

    # --- Step 1: Run Gate on Risk 1 (FIRE NUDGE) ---
    d1 = run_gate(conn, r1_id)

    # --- Step 2: Run Gate on Risk 2 (STAY SILENT - Materiality Fail) ---
    d2 = run_gate(conn, r2_id)

    # --- Step 3: Run Gate AGAIN on Risk 1 (STAY SILENT - Timing Fail) ---
    d3 = run_gate(conn, r1_id)

    # --- Step 4: Verify and Count Decision Nodes in Graph ---
    decision_nodes = find_nodes(conn, type="decision")

    console.print(f"\n[bold green]Total Decision Nodes in Knowledge Graph:[/bold green] [bold yellow]{len(decision_nodes)}[/bold yellow]\n")

    # --- Step 5: Side-by-side Decision Output ---
    decisions = [d1, d2, d3]
    for idx, d in enumerate(decisions, start=1):
        verdict = "[bold green]FIRE NUDGE[/bold green]" if d["final_verdict"] else "[bold red]STAY SILENT[/bold red]"
        mat = "[green]PASS[/green]" if d["materiality_result"] else "[red]FAIL[/red]"
        tim = "[green]PASS[/green]" if d["timing_result"] else "[red]FAIL[/red]"
        spec = "[green]PASS[/green]" if d["specificity_result"] else "[red]FAIL[/red]"

        panel_content = (
            f"Decision Node ID : #{d['id']}\n"
            f"Target Risk Node : #{d['risk_id']}\n"
            f"Verdict          : {verdict}\n"
            f"Checks           : Materiality={mat} | Timing={tim} | Specificity={spec}\n\n"
            f"[bold white]Detailed Reasoning:[/bold white]\n{d['combined_reasoning']}"
        )
        console.print(Panel(panel_content, title=f"Gate Execution {idx}"))

    table = Table(title="Intervention Gate Summary Matrix", show_lines=True)
    table.add_column("Decision ID", justify="right", style="cyan")
    table.add_column("Risk Target", style="bold white")
    table.add_column("Verdict", style="bold")
    table.add_column("Mat", style="magenta")
    table.add_column("Tim", style="yellow")
    table.add_column("Spec", style="blue")

    for d in decisions:
        did = str(d["id"])
        rid = f"Risk #{d['risk_id']}"
        verdict = "[bold green]FIRE NUDGE[/bold green]" if d["final_verdict"] else "[bold red]STAY SILENT[/bold red]"
        mat = "[green]PASS[/green]" if d["materiality_result"] else "[red]FAIL[/red]"
        tim = "[green]PASS[/green]" if d["timing_result"] else "[red]FAIL[/red]"
        spec = "[green]PASS[/green]" if d["specificity_result"] else "[red]FAIL[/red]"
        table.add_row(did, rid, verdict, mat, tim, spec)

    console.print(table)

    conn.close()
    if db_path.exists():
        db_path.unlink()


if __name__ == "__main__":
    main()
