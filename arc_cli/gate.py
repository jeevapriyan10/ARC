"""
Intervention Gate for ARC CLI.

Evaluates unresolved risk nodes against three gate criteria:
1. Materiality (impact / dependents / passed deadline)
2. Timing (nudge anti-spam window)
3. Specificity (identifiable milestone and context)

When all checks pass (FIRE NUDGE), drafts a specific nudge message via LLM
and delivers it to Slack via incoming webhook.
"""

from datetime import datetime, timezone
import os
import sqlite3
from typing import Any, Dict, Optional, Tuple
from dotenv import load_dotenv
import requests
import typer

from arc_cli.graph import (
    add_edge,
    add_node,
    find_nodes,
    get_current_time,
    get_edges_from,
    get_edges_to,
    get_node,
    traverse_dependents,
)
from arc_cli.llm import draft_nudge_message


def _get_milestone_for_risk(
    conn: sqlite3.Connection, risk_node_id: int
) -> Tuple[Optional[Dict[str, Any]], Optional[int]]:
    """Helper to locate the milestone node associated with a risk node.

    Returns:
        (milestone_node_dict, milestone_id) or (None, None) if not found.
    """
    risk_node = get_node(conn, risk_node_id)
    if not risk_node:
        return None, None

    props = risk_node.get("properties", {})
    m_id = props.get("milestone_id")
    if m_id is not None:
        m_node = get_node(conn, int(m_id))
        if m_node and m_node.get("type") == "milestone":
            return m_node, m_node["id"]

    # Check incoming edges to risk (e.g. milestone --causes--> risk)
    incoming_edges = get_edges_to(conn, risk_node_id)
    for edge in incoming_edges:
        source_node = get_node(conn, edge["source_id"])
        if source_node and source_node.get("type") == "milestone":
            return source_node, source_node["id"]

    # Check outgoing edges from risk (e.g. risk --links_to/depends_on--> milestone)
    outgoing_edges = get_edges_from(conn, risk_node_id)
    for edge in outgoing_edges:
        target_node = get_node(conn, edge["target_id"])
        if target_node and target_node.get("type") == "milestone":
            return target_node, target_node["id"]

    return None, None


def materiality(conn: sqlite3.Connection, risk_node_id: int) -> Tuple[bool, str]:
    """1. Materiality check:
    Find the milestone this risk is linked to.
    Call traverse_dependents() from graph.py to find how many OTHER milestones depend on it.
    Materiality is True if 1+ dependents exist, OR if the milestone's deadline has already passed
    (even with no dependents). Returns reasoning as a human-readable string either way.
    """
    m_node, m_id = _get_milestone_for_risk(conn, risk_node_id)
    if not m_node or m_id is None:
        return False, f"Risk node #{risk_node_id} has no linked milestone."

    m_label = m_node.get("label", f"Milestone #{m_id}")
    m_props = m_node.get("properties", {})

    dependents = traverse_dependents(conn, m_id)
    num_dependents = len(dependents)

    # Check deadline
    now = get_current_time(conn)
    deadline_hours = float(m_props.get("deadline_hours", 0))
    created_at_str = m_node.get("created_at")

    elapsed_hours = 0.0
    if created_at_str:
        try:
            created_dt = datetime.fromisoformat(created_at_str)
            if created_dt.tzinfo is None:
                created_dt = created_dt.replace(tzinfo=timezone.utc)
            elapsed_hours = (now - created_dt).total_seconds() / 3600.0
        except Exception:
            elapsed_hours = 0.0

    deadline_passed = (elapsed_hours > deadline_hours) or (m_props.get("status") == "overdue")

    is_material = (num_dependents >= 1) or deadline_passed

    if num_dependents >= 1 and deadline_passed:
        reasoning = (
            f"Milestone '{m_label}' has {num_dependents} dependent milestone(s) "
            f"and deadline has passed ({elapsed_hours:.1f}h elapsed > {deadline_hours:.1f}h deadline)."
        )
    elif num_dependents >= 1:
        reasoning = f"Milestone '{m_label}' has {num_dependents} dependent milestone(s)."
    elif deadline_passed:
        reasoning = (
            f"Milestone '{m_label}' deadline has passed ({elapsed_hours:.1f}h elapsed > {deadline_hours:.1f}h deadline), "
            f"though it has 0 dependents."
        )
    else:
        reasoning = (
            f"Milestone '{m_label}' has 0 dependents and deadline has not passed "
            f"({elapsed_hours:.1f}h elapsed <= {deadline_hours:.1f}h deadline)."
        )

    return is_material, reasoning


def timing(conn: sqlite3.Connection, risk_node_id: int, hours: float = 4.0) -> Tuple[bool, str]:
    """2. Timing check:
    Check nudge history (query 'decision' nodes with type='decision' related to this risk/milestone).
    Has a nudge already fired for this exact risk in the last N hours (default 4)?
    If so, timing fails (avoid spamming). Otherwise timing passes.
    """
    now = get_current_time(conn)
    m_node, m_id = _get_milestone_for_risk(conn, risk_node_id)

    decision_nodes = find_nodes(conn, type="decision")

    for d in decision_nodes:
        d_props = d.get("properties", {})

        # Match exact risk ID or milestone ID
        d_risk_id = d_props.get("risk_id")
        matches_risk = (d_risk_id == risk_node_id)

        if not matches_risk:
            edges = get_edges_from(conn, d["id"], relation="decided_by")
            matches_risk = any(e["target_id"] == risk_node_id for e in edges)

        if matches_risk:
            fired = (
                d_props.get("final_verdict") is True
                or d_props.get("final_verdict") == "fire"
                or d_props.get("should_fire") is True
            )
            if fired:
                c_str = d.get("created_at")
                if c_str:
                    try:
                        cdt = datetime.fromisoformat(c_str)
                        if cdt.tzinfo is None:
                            cdt = cdt.replace(tzinfo=timezone.utc)
                        elapsed = (now - cdt).total_seconds() / 3600.0
                        if elapsed < hours:
                            return (
                                False,
                                f"A nudge already fired for risk node #{risk_node_id} within the last {hours:.1f} hours ({elapsed:.1f}h ago).",
                            )
                    except Exception:
                        pass

    return True, f"No nudge has fired for risk node #{risk_node_id} in the last {hours:.1f} hours."


def specificity(conn: sqlite3.Connection, risk_node_id: int) -> Tuple[bool, str]:
    """3. Specificity check:
    Can we name an exact milestone, and (if available) an exact recent commit or file?
    If we only have a vague "something is behind" signal with no linked milestone, specificity fails.
    """
    m_node, m_id = _get_milestone_for_risk(conn, risk_node_id)
    if not m_node or m_id is None:
        return False, f"Vague risk signal without a linked milestone (risk node #{risk_node_id})."

    m_label = m_node.get("label", f"Milestone #{m_id}")

    # Look for linked recent commit or file
    recent_info = ""
    touch_edges = get_edges_to(conn, m_id, relation="touches")
    if touch_edges:
        latest_edge = touch_edges[-1]
        commit_node = get_node(conn, latest_edge["source_id"])
        if commit_node:
            c_label = commit_node.get("label", "Commit")
            c_files = commit_node.get("properties", {}).get("files", [])
            file_str = f" file: {c_files[0]}" if c_files else ""
            recent_info = f" (recent commit: {c_label}{file_str})"
    else:
        all_commits = find_nodes(conn, type="commit")
        if all_commits:
            latest_commit = all_commits[-1]
            c_label = latest_commit.get("label", "Commit")
            c_files = latest_commit.get("properties", {}).get("files", [])
            file_str = f" file: {c_files[0]}" if c_files else ""
            recent_info = f" (latest repository commit: {c_label}{file_str})"

    return True, f"Specific milestone identified: '{m_label}'{recent_info}."


def post_slack_nudge(webhook_url: Optional[str], message: str) -> bool:
    """Post a nudge message to Slack incoming webhook URL using requests.

    Gracefully handles network errors, bad URLs, missing env vars, and HTTP errors.

    Args:
        webhook_url: Slack incoming webhook URL.
        message: The nudge message text to post.

    Returns:
        True if HTTP POST succeeded with status 200, False otherwise.
    """
    if not webhook_url or not webhook_url.strip():
        typer.echo("[Slack Nudge Warning] SLACK_WEBHOOK_URL is not configured.", err=True)
        return False

    try:
        payload = {"text": message}
        resp = requests.post(webhook_url, json=payload, timeout=5)
        if resp.status_code == 200 and resp.text.strip().lower() == "ok":
            typer.echo("[Slack Nudge OK] Nudge delivered successfully to Slack!")
            return True
        else:
            typer.echo(f"[Slack Nudge Error] Failed to post to Slack (HTTP {resp.status_code}): {resp.text}", err=True)
            return False
    except Exception as exc:
        typer.echo(f"[Slack Nudge Network Error] Could not connect to Slack webhook: {exc}", err=True)
        return False


def run_gate(conn: sqlite3.Connection, risk_node_id: int, hours: float = 4.0) -> Dict[str, Any]:
    """Runs all three gate checks, records a decision node in the graph,
    and if final_verdict is FIRE NUDGE, drafts & posts a Slack nudge message.

    On successful Slack delivery, records a 'nudge' node linked to the decision node.
    Does NOT auto-resolve the risk node.
    """
    load_dotenv()

    mat_pass, mat_reason = materiality(conn, risk_node_id)
    tim_pass, tim_reason = timing(conn, risk_node_id, hours=hours)
    spec_pass, spec_reason = specificity(conn, risk_node_id)

    final_verdict = mat_pass and tim_pass and spec_pass
    verdict_str = "FIRE NUDGE" if final_verdict else "STAY SILENT"

    combined_reasoning = (
        f"Verdict: {verdict_str}. "
        f"Materiality: [{'PASS' if mat_pass else 'FAIL'}] {mat_reason} | "
        f"Timing: [{'PASS' if tim_pass else 'FAIL'}] {tim_reason} | "
        f"Specificity: [{'PASS' if spec_pass else 'FAIL'}] {spec_reason}"
    )

    decision_props = {
        "risk_id": risk_node_id,
        "materiality_result": mat_pass,
        "timing_result": tim_pass,
        "specificity_result": spec_pass,
        "final_verdict": final_verdict,
        "combined_reasoning": combined_reasoning,
    }

    decision_label = f"Decision for Risk #{risk_node_id}: {verdict_str}"
    decision_node_id = add_node(
        conn,
        type="decision",
        label=decision_label,
        properties=decision_props,
    )

    add_edge(
        conn,
        source_id=decision_node_id,
        target_id=risk_node_id,
        relation="decided_by",
    )

    nudge_sent = False
    nudge_node_id = None
    nudge_message = ""

    if final_verdict:
        m_node, m_id = _get_milestone_for_risk(conn, risk_node_id)
        m_name = m_node.get("label", f"Milestone #{m_id}") if m_node else "Milestone"

        try:
            nudge_message = draft_nudge_message(
                reasoning=combined_reasoning,
                milestone_name=m_name,
            )
        except Exception:
            nudge_message = (
                f"🚨 *ARC Risk Alert*: Milestone *{m_name}* requires immediate attention. "
                f"{combined_reasoning}"
            )

        webhook_url = os.getenv("SLACK_WEBHOOK_URL")
        nudge_sent = post_slack_nudge(webhook_url, nudge_message)

        if nudge_sent:
            now_iso = get_current_time(conn).isoformat()
            nudge_props = {
                "message": nudge_message,
                "timestamp": now_iso,
                "milestone_id": m_id,
            }
            nudge_node_id = add_node(
                conn,
                type="nudge",
                label=f"Nudge: {m_name}",
                properties=nudge_props,
            )
            add_edge(
                conn,
                source_id=decision_node_id,
                target_id=nudge_node_id,
                relation="links_to",
            )

    return {
        "id": decision_node_id,
        "risk_id": risk_node_id,
        "materiality_result": mat_pass,
        "materiality_reasoning": mat_reason,
        "timing_result": tim_pass,
        "timing_reasoning": tim_reason,
        "specificity_result": spec_pass,
        "specificity_reasoning": spec_reason,
        "final_verdict": final_verdict,
        "should_fire": final_verdict,
        "combined_reasoning": combined_reasoning,
        "nudge_sent": nudge_sent,
        "nudge_node_id": nudge_node_id,
        "nudge_message": nudge_message,
    }
