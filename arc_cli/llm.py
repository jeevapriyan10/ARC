"""
Local LLM module for ARC CLI.

Provides local model inference (offline) using Hugging Face transformers
or local Ollama endpoints.
"""

import json
import os
import re
import urllib.request
from typing import Any, Dict, List, Optional
from dotenv import load_dotenv


def generate_plan_response(context: str, model_name: Optional[str] = None) -> str:
    """Generate project milestone plan response from local LLM.

    Args:
        context: Concatenated project context string from ingest.
        model_name: Optional model name override.

    Returns:
        Raw LLM text response.
    """
    load_dotenv()

    messages = [
        {
            "role": "system",
            "content": (
                "You are an expert software project planning assistant. "
                "You MUST output ONLY a valid JSON object matching the requested schema. "
                "Do not include markdown code fences, preambles, or explanations."
            ),
        },
        {
            "role": "user",
            "content": (
                "Analyze the project context provided and generate a sequential list of software development milestones.\n\n"
                "JSON shape required:\n"
                "{\n"
                '  "milestones": [\n'
                '    {\n'
                '      "name": "Milestone Title",\n'
                '      "owner": "Role or Developer",\n'
                '      "deadline_hours": 12,\n'
                '      "depends_on": ["Previous Milestone Title"]\n'
                "    }\n"
                "  ]\n"
                "}\n\n"
                f"Project Context:\n---\n{context}\n---"
            ),
        },
    ]

    # 1. Check if local Ollama server is specified or running
    ollama_url = os.getenv("ARC_OLLAMA_URL")
    if ollama_url or _check_ollama_available():
        endpoint = ollama_url.rstrip("/") if ollama_url else "http://localhost:11434"
        try:
            req_data = json.dumps({
                "model": os.getenv("ARC_OLLAMA_MODEL", "qwen2.5:0.5b"),
                "messages": messages,
                "stream": False,
            }).encode("utf-8")
            req = urllib.request.Request(
                f"{endpoint}/api/chat",
                data=req_data,
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            with urllib.request.urlopen(req, timeout=10) as resp:
                data = json.loads(resp.read().decode("utf-8"))
                if "message" in data and "content" in data["message"]:
                    return data["message"]["content"]
        except Exception:
            pass

    # 2. Local Hugging Face transformers pipeline
    from transformers import pipeline

    if not model_name:
        model_name = os.getenv("ARC_LLM_MODEL", "Qwen/Qwen2.5-0.5B-Instruct")

    pipe = pipeline("text-generation", model=model_name, max_new_tokens=600, return_full_text=False)
    results = pipe(messages)
    if results and len(results) > 0 and "generated_text" in results[0]:
        gen = results[0]["generated_text"]
        if isinstance(gen, list) and len(gen) > 0 and isinstance(gen[-1], dict):
            return gen[-1].get("content", "")
        elif isinstance(gen, str):
            return gen

    raise RuntimeError("Failed to generate response from local LLM.")


def _check_ollama_available() -> bool:
    try:
        req = urllib.request.Request("http://localhost:11434/api/tags")
        with urllib.request.urlopen(req, timeout=1) as resp:
            return resp.status == 200
    except Exception:
        return False


def parse_plan_json(response_text: str) -> List[Dict[str, Any]]:
    """Parse JSON response from LLM defensively.

    Strips markdown code fences and extraneous text surrounding the JSON.

    Args:
        response_text: Raw response string from LLM.

    Returns:
        List of milestone dictionaries.

    Raises:
        ValueError: If JSON cannot be parsed or lacks required structure.
    """
    cleaned = response_text.strip()

    # Strip markdown code fences if present
    fence_pattern = r"```(?:json)?\s*([\s\S]*?)\s*```"
    match = re.search(fence_pattern, cleaned, re.IGNORECASE)
    if match:
        cleaned = match.group(1).strip()

    # Extract JSON object from first '{' to last '}'
    start_idx = cleaned.find("{")
    end_idx = cleaned.rfind("}")
    if start_idx != -1 and end_idx != -1 and end_idx > start_idx:
        cleaned = cleaned[start_idx : end_idx + 1]

    try:
        data = json.loads(cleaned)
    except Exception as e:
        raise ValueError(f"Could not parse response as valid JSON: {e}\nRaw output: {response_text}")

    if not isinstance(data, dict) or "milestones" not in data:
        raise ValueError("JSON response must contain a top-level 'milestones' key.")

    milestones = data.get("milestones", [])
    if not isinstance(milestones, list):
        raise ValueError("'milestones' field must be a list.")

    return milestones


def draft_nudge_message(
    reasoning: str,
    milestone_name: str,
    model_name: Optional[str] = None,
) -> str:
    """Draft a short, specific nudge message (1-3 sentences) using local LLM.

    Args:
        reasoning: Combined reasoning from intervention gate checks.
        milestone_name: Name of the target milestone.
        model_name: Optional model override.

    Returns:
        Specific nudge message text (1-3 sentences).
    """
    load_dotenv()

    system_prompt = (
        "You are ARC, an automated AI project coordinator. "
        "Draft a short, urgent, highly specific Slack nudge message (1 to 3 sentences max) to alert the development team to a risk. "
        "Do NOT use generic boilerplate. Explicitly reference the milestone name and dependency impact provided in the reasoning."
    )
    user_prompt = (
        f"Milestone: {milestone_name}\n"
        f"Decision Reasoning: {reasoning}\n\n"
        "Draft the specific 1-3 sentence Slack nudge:"
    )

    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_prompt},
    ]

    # 1. Local Ollama endpoint
    ollama_url = os.getenv("ARC_OLLAMA_URL")
    if ollama_url or _check_ollama_available():
        endpoint = ollama_url.rstrip("/") if ollama_url else "http://localhost:11434"
        try:
            req_data = json.dumps({
                "model": os.getenv("ARC_OLLAMA_MODEL", "qwen2.5:0.5b"),
                "messages": messages,
                "stream": False,
            }).encode("utf-8")
            req = urllib.request.Request(
                f"{endpoint}/api/chat",
                data=req_data,
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            with urllib.request.urlopen(req, timeout=5) as resp:
                data = json.loads(resp.read().decode("utf-8"))
                if "message" in data and "content" in data["message"]:
                    res_text = data["message"]["content"].strip()
                    if res_text:
                        return res_text
        except Exception:
            pass

    # 2. Local Hugging Face transformers pipeline if explicitly configured
    if model_name or os.getenv("ARC_LLM_MODEL") or os.getenv("ARC_USE_TRANSFORMERS") == "1":
        try:
            from transformers import pipeline

            if not model_name:
                model_name = os.getenv("ARC_LLM_MODEL", "Qwen/Qwen2.5-0.5B-Instruct")

            pipe = pipeline("text-generation", model=model_name, max_new_tokens=150, return_full_text=False)
            results = pipe(messages)
            if results and len(results) > 0 and "generated_text" in results[0]:
                gen = results[0]["generated_text"]
                if isinstance(gen, list) and len(gen) > 0 and isinstance(gen[-1], dict):
                    text = gen[-1].get("content", "").strip()
                    if text:
                        return text
                elif isinstance(gen, str) and gen.strip():
                    return gen.strip()
        except Exception:
            pass

    # Fallback to specific structured message referencing milestone & reasoning
    return (
        f"[ARC Risk Alert]: Milestone '{milestone_name}' requires immediate attention. "
        f"{reasoning} Please check status and push updates to unblock dependent milestones."
    )


def generate_report_response(context: str, model_name: Optional[str] = None) -> str:
    """Generate pitch readiness and status report from project graph context using local LLM.

    Args:
        context: Synthesized project graph context string.
        model_name: Optional model override.

    Returns:
        Markdown report string.
    """
    load_dotenv()

    system_prompt = (
        "You are ARC, an expert AI project management assistant. "
        "Analyze the project graph context provided and write a clean, structured Markdown report with 3 sections:\n"
        "1. Pitch-Readiness Summary (Factual summary of what is built vs planned based on milestone statuses and commits)\n"
        "2. Blocker Digest (Plainly stated list of unresolved risks and intervention decisions)\n"
        "3. Short Pitch Outline (Problem, What We Built, Demo Flow, What's Next)\n\n"
        "Be concise, professional, and base your analysis strictly on the provided context."
    )
    user_prompt = f"Project Context:\n---\n{context}\n---"

    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_prompt},
    ]

    # 1. Local Ollama endpoint
    ollama_url = os.getenv("ARC_OLLAMA_URL")
    if ollama_url or _check_ollama_available():
        endpoint = ollama_url.rstrip("/") if ollama_url else "http://localhost:11434"
        try:
            req_data = json.dumps({
                "model": os.getenv("ARC_OLLAMA_MODEL", "qwen2.5:0.5b"),
                "messages": messages,
                "stream": False,
            }).encode("utf-8")
            req = urllib.request.Request(
                f"{endpoint}/api/chat",
                data=req_data,
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            with urllib.request.urlopen(req, timeout=10) as resp:
                data = json.loads(resp.read().decode("utf-8"))
                if "message" in data and "content" in data["message"]:
                    res_text = data["message"]["content"].strip()
                    if res_text:
                        return res_text
        except Exception:
            pass

    # 2. Local Hugging Face transformers pipeline if explicitly configured
    if model_name or os.getenv("ARC_LLM_MODEL") or os.getenv("ARC_USE_TRANSFORMERS") == "1":
        try:
            from transformers import pipeline

            if not model_name:
                model_name = os.getenv("ARC_LLM_MODEL", "Qwen/Qwen2.5-0.5B-Instruct")

            pipe = pipeline("text-generation", model=model_name, max_new_tokens=800, return_full_text=False)
            results = pipe(messages)
            if results and len(results) > 0 and "generated_text" in results[0]:
                gen = results[0]["generated_text"]
                if isinstance(gen, list) and len(gen) > 0 and isinstance(gen[-1], dict):
                    text = gen[-1].get("content", "").strip()
                    if text:
                        return text
                elif isinstance(gen, str) and gen.strip():
                    return gen.strip()
        except Exception:
            pass

    # Fallback structured Markdown report generated directly from context
    return _generate_fallback_report(context)


def _generate_fallback_report(context: str) -> str:
    """Fallback generator for report markdown when no LLM endpoint is active."""
    return f"""# ARC Executive Status & Pitch-Readiness Report

## 1. Pitch-Readiness Summary
This report reflects the current state of project milestones, git commit activity, and active risk signals in the ARC Knowledge Graph.

### Context Snapshot
```text
{context}
```

## 2. Blocker Digest
- Review unresolved risk nodes and intervention decisions in the context snapshot above.
- Ensure high-materiality overdue milestones receive team focus before pitch freeze.

## 3. Short Pitch Outline
- **Problem**: Project drift, hidden dependencies, and silent milestone delays in fast-paced software development and hackathons.
- **What We Built**: ARC CLI — a lightweight Knowledge Graph engine providing automated git tracking, drift detection, and gate interventions.
- **Demo Flow**:
  1. `arc ingest` project context & `arc plan` milestones.
  2. `arc watch` git commits to automatically track code progress against milestones.
  3. `arc status` to evaluate drift detection and trigger Slack nudges.
  4. `arc report` to review pitch readiness and blocker digest.
- **What's Next**: Automated code remediation, multi-channel alerting, and real-time team dashboards.
"""
