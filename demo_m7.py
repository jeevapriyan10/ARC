"""
Module 7 Nudge Delivery (Slack) Demo Script.

Demonstrates:
1. LLM Nudge drafting (specific, 1-3 sentences, references actual milestone & dependencies)
2. Slack Webhook POST delivery
3. 'nudge' node creation & 'links_to' edge linkage in knowledge graph
4. Non-auto-resolution of risk node (resolved remains False)
5. Graceful network error handling on bad/broken webhook URL
"""

import sys
if hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass

from datetime import datetime, timedelta, timezone
from pathlib import Path
import sqlite3
from unittest.mock import MagicMock, patch

from rich.console import Console
from rich.panel import Panel

from arc_cli.gate import run_gate
from arc_cli.graph import (
    add_edge,
    add_node,
    find_nodes,
    get_edges_from,
    get_node,
    init_graph_schema,
)


def main():
    console = Console()
    console.print(Panel.fit("[bold cyan]ARC Module 7 - Slack Nudge Delivery Demo[/bold cyan]"))

    db_path = Path("demo_m7.db")
    if db_path.exists():
        db_path.unlink()

    conn = sqlite3.connect(db_path)
    init_graph_schema(conn)

    now = datetime.now(timezone.utc)
    old_time = (now - timedelta(hours=12)).isoformat()

    # --- Setup Knowledge Graph Data ---
    m_auth = add_node(
        conn,
        type="milestone",
        label="Authentication Service API",
        properties={"owner": "Alice", "deadline_hours": 3, "status": "in_progress"},
    )
    conn.cursor().execute("UPDATE nodes SET created_at = ? WHERE id = ?", (old_time, m_auth))

    m_dash = add_node(
        conn,
        type="milestone",
        label="User Dashboard UI",
        properties={"owner": "Bob", "deadline_hours": 12, "status": "not_started"},
    )
    add_edge(conn, source_id=m_dash, target_id=m_auth, relation="depends_on")

    m_bill = add_node(
        conn,
        type="milestone",
        label="Billing Gateway Integration",
        properties={"owner": "Charlie", "deadline_hours": 16, "status": "not_started"},
    )
    add_edge(conn, source_id=m_bill, target_id=m_auth, relation="depends_on")

    r_auth = add_node(
        conn,
        type="risk",
        label="Overdue: Authentication Service API",
        properties={"signal": "milestone_overdue", "severity": "high", "milestone_id": m_auth, "resolved": False},
    )
    add_edge(conn, source_id=m_auth, target_id=r_auth, relation="causes")
    conn.commit()

    # --- Scenario 1: Successful Nudge Delivery to Slack ---
    console.print("\n[bold yellow]Scenario 1: Successful Slack Webhook Delivery[/bold yellow]")

    with patch("requests.post") as mock_post:
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.text = "ok"
        mock_post.return_value = mock_resp

        with patch.dict("os.environ", {"SLACK_WEBHOOK_URL": "https://hooks.slack.com/services/DEMO/WEBHOOK"}):
            decision1 = run_gate(conn, r_auth)

    console.print(f"Verdict         : [bold green]{'FIRE NUDGE' if decision1['final_verdict'] else 'STAY SILENT'}[/bold green]")
    console.print(f"Slack Delivered : [bold green]{decision1['nudge_sent']}[/bold green]")
    console.print(f"Drafted Message : [white]{decision1['nudge_message']}[/white]")

    nudge_nodes = find_nodes(conn, type="nudge")
    console.print(f"Nudge Node Created: ID #{decision1['nudge_node_id']} (Total nudge nodes in graph: {len(nudge_nodes)})")

    links = get_edges_from(conn, decision1["id"], relation="links_to")
    console.print(f"Edge Created    : Decision #{decision1['id']} --links_to--> Nudge #{links[0]['target_id']}")

    r_state = get_node(conn, r_auth)
    console.print(f"Risk Resolved   : [bold cyan]{r_state['properties']['resolved']}[/bold cyan] (Risk correctly left unresolved)")

    # --- Scenario 2: Graceful Failure with Bad Webhook URL ---
    console.print("\n[bold yellow]Scenario 2: Network / Webhook Failure (Bad Webhook URL)[/bold yellow]")

    with patch("requests.post") as mock_post_err:
        mock_post_err.side_effect = Exception("Connection refused / Timeout to https://hooks.slack.com/bad_url")

        with patch.dict("os.environ", {"SLACK_WEBHOOK_URL": "https://hooks.slack.com/services/INVALID/URL"}):
            # Run gate again (hours=0.0 to bypass timing check for demo)
            decision2 = run_gate(conn, r_auth, hours=0.0)

    console.print(f"Verdict         : [bold green]{'FIRE NUDGE' if decision2['final_verdict'] else 'STAY SILENT'}[/bold green]")
    console.print(f"Slack Delivered : [bold red]{decision2['nudge_sent']}[/bold red]")
    console.print("[bold green]System survived network error gracefully without crashing![/bold green]")

    conn.close()
    if db_path.exists():
        db_path.unlink()


if __name__ == "__main__":
    main()
