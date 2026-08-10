from datetime import datetime, timedelta, timezone
import sqlite3
from unittest.mock import MagicMock, patch
import requests

from arc_cli.gate import (
    post_slack_nudge,
    run_gate,
)
from arc_cli.graph import (
    add_edge,
    add_node,
    find_nodes,
    get_edges_from,
    get_node,
    init_graph_schema,
)
from arc_cli.llm import draft_nudge_message


def test_draft_nudge_message_fallback():
    msg = draft_nudge_message(
        reasoning="Milestone 'Core API' has 2 dependents.",
        milestone_name="Core API",
    )
    assert "Core API" in msg
    assert len(msg) > 10


def test_post_slack_nudge_success():
    with patch("requests.post") as mock_post:
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.text = "ok"
        mock_post.return_value = mock_resp

        res = post_slack_nudge("http://example.com/webhook", "Hello team")
        assert res is True
        mock_post.assert_called_once_with(
            "http://example.com/webhook",
            json={"text": "Hello team"},
            timeout=5,
        )


def test_post_slack_nudge_network_error():
    with patch("requests.post") as mock_post:
        mock_post.side_effect = requests.RequestException("Connection refused")

        res = post_slack_nudge("http://invalid.url/webhook", "Test message")
        assert res is False


def test_run_gate_fires_and_creates_nudge_node(tmp_path, monkeypatch):
    monkeypatch.setenv("SLACK_WEBHOOK_URL", "https://hooks.slack.com/services/TEST/MOCK")

    db_path = tmp_path / "arc.db"
    conn = sqlite3.connect(db_path)
    init_graph_schema(conn)

    now = datetime.now(timezone.utc)
    old_time = (now - timedelta(hours=10)).isoformat()

    m_id = add_node(
        conn,
        type="milestone",
        label="Payment Gateway",
        properties={"deadline_hours": 2, "owner": "Alice", "status": "in_progress"},
    )
    conn.cursor().execute("UPDATE nodes SET created_at = ? WHERE id = ?", (old_time, m_id))

    m_dep = add_node(
        conn,
        type="milestone",
        label="Checkout UI",
        properties={"deadline_hours": 20, "owner": "Bob", "status": "not_started"},
    )
    add_edge(conn, source_id=m_dep, target_id=m_id, relation="depends_on")

    r_id = add_node(
        conn,
        type="risk",
        label="Overdue: Payment Gateway",
        properties={"signal": "milestone_overdue", "milestone_id": m_id, "resolved": False},
    )
    add_edge(conn, source_id=m_id, target_id=r_id, relation="causes")
    conn.commit()

    with patch("requests.post") as mock_post:
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.text = "ok"
        mock_post.return_value = mock_resp

        res = run_gate(conn, r_id)

    assert res["final_verdict"] is True
    assert res["nudge_sent"] is True
    assert res["nudge_node_id"] is not None

    # Check nudge node created in graph
    nudge_nodes = find_nodes(conn, type="nudge")
    assert len(nudge_nodes) == 1
    n_node = nudge_nodes[0]
    assert n_node["properties"]["milestone_id"] == m_id
    assert "Payment Gateway" in n_node["properties"]["message"]

    # Check edge from decision node to nudge node
    d_edges = get_edges_from(conn, res["id"], relation="links_to")
    assert len(d_edges) == 1
    assert d_edges[0]["target_id"] == n_node["id"]

    # Confirm risk node is NOT auto-resolved (resolved remains False)
    r_node = get_node(conn, r_id)
    assert r_node["properties"]["resolved"] is False

    conn.close()


def test_run_gate_graceful_failure_with_bad_webhook(tmp_path, monkeypatch):
    monkeypatch.setenv("SLACK_WEBHOOK_URL", "https://hooks.slack.com/services/BAD/URL")

    db_path = tmp_path / "arc.db"
    conn = sqlite3.connect(db_path)
    init_graph_schema(conn)

    now = datetime.now(timezone.utc)
    old_time = (now - timedelta(hours=10)).isoformat()

    m_id = add_node(
        conn,
        type="milestone",
        label="Auth Service",
        properties={"deadline_hours": 2, "owner": "Charlie", "status": "in_progress"},
    )
    conn.cursor().execute("UPDATE nodes SET created_at = ? WHERE id = ?", (old_time, m_id))

    r_id = add_node(
        conn,
        type="risk",
        label="Overdue: Auth Service",
        properties={"signal": "milestone_overdue", "milestone_id": m_id, "resolved": False},
    )
    add_edge(conn, source_id=m_id, target_id=r_id, relation="causes")
    conn.commit()

    with patch("requests.post") as mock_post:
        mock_post.side_effect = requests.RequestException("Connection error")

        res = run_gate(conn, r_id)

    # Should not crash, decision node created, nudge_sent is False, 0 nudge nodes created
    assert res["final_verdict"] is True
    assert res["nudge_sent"] is False

    nudge_nodes = find_nodes(conn, type="nudge")
    assert len(nudge_nodes) == 0

    conn.close()
