# ARC CLI — Autonomous Reasoning & Intervention Engine

ARC is an offline-first Knowledge Graph CLI companion built for fast-paced software development and hackathons. It continuously monitors project progress, links git commit activity to plan milestones, detects drift, and applies a strict 3-rule intervention gate before alerting team channels.

---

## Key Features

- **Knowledge Graph Core**: Uses SQLite to model milestones, code commits, drift risks, gate decisions, and context memory.
- **Automated Git Integration**: `arc watch` installs a git post-commit hook that automatically links modified files to project milestones.
- **Drift & Inactivity Heartbeat**: Detects overdue deadlines and commit silence on critical path tasks.
- **3-Rule Intervention Gate**: Prevents alert fatigue by filtering risks through **Materiality**, **Timing**, and **Specificity** checks before firing nudges.
- **Local LLM Integration**: Generates structured milestone plans, specific Slack nudge messages, and pitch-readiness summaries without requiring cloud AI dependencies (supports local Ollama or Hugging Face transformers with offline fallback).
- **Time-Aware Demo Mode**: Scripted timeline replay engine using a virtual project clock for instant 2-minute live demonstrations.

---

## Quickstart & Installation

### Prerequisites
- Python 3.9+
- Git

### Installation
Clone the repository and install in editable mode:

```bash
git clone https://github.com/jeevapriyan10/ARC.git
cd ARC
pip install -e .
```

Verify installation:
```bash
arc --help
```

---

## Command Reference

| Command | Usage | Description |
|---|---|---|
| `init` | `arc init` | Initializes the `.arc/arc.db` SQLite Knowledge Graph schema. |
| `ingest` | `arc ingest <files...>` | Ingests problem statements or README docs into graph `memory` nodes. |
| `plan` | `arc plan [--model M]` | Parses ingested context using local LLM to generate structured milestones and dependency edges. |
| `watch` | `arc watch` | Installs `.git/hooks/post-commit` to automatically track commits in ARC graph. |
| `status` | `arc status [--silence-hours 4.0]` | Displays milestone progress, drift warnings, active risks, and intervention gate verdicts. |
| `report` | `arc report [--model M]` | Synthesizes project state into `.arc/report.md` (Pitch Readiness, Blocker Digest, Pitch Outline). |
| `demo` | `arc demo <script.json> [--delay S]` | Replays a simulated project timeline with virtual project clock for live presentations. |

---

## Knowledge Graph Architecture

ARC models software projects as a directed property graph stored locally in SQLite (`.arc/arc.db`).

### Node Types
- `milestone`: Target project goals with owners, deadlines, and completion statuses (`not_started`, `in_progress`, `completed`).
- `commit`: Recorded git commit hashes, timestamps, and touched file lists.
- `risk`: Flagged drift signals (`milestone_overdue`, `commit_silence`).
- `decision`: Evaluation records from the intervention gate (`FIRE NUDGE` vs `STAY SILENT`).
- `nudge`: Sent alert logs with timestamps and delivered text.
- `memory`: Ingested document content and generated report contexts.

### Edge Relations
- `depends_on`: Connects dependent milestones (`Milestone B --depends_on--> Milestone A`).
- `touches`: Connects commits to impacted milestones (`Commit C --touches--> Milestone A`).
- `causes`: Connects overdue milestones to generated risk nodes (`Milestone A --causes--> Risk R`).
- `links_to`: Connects gate decisions to dispatched nudge logs (`Decision D --links_to--> Nudge N`).

---

## Intervention Gate Logic

To eliminate spam and deliver actionable nudges, every risk signal must pass all three gate criteria:

1. **Materiality**: Verifies whether the risk affects a milestone with downstream dependents or an overdue deadline.
2. **Timing**: Enforces a 4-hour anti-spam window per risk signal to prevent repeated notifications.
3. **Specificity**: Ensures the alert identifies a concrete milestone and code context rather than generic warnings.

---

## Scripted Demo Timeline

To showcase ARC's judgment loop in a 2-minute live demo:

```bash
arc demo demo_scenario.json --delay 0.5
```

This runs a simulated timeline replay using a virtual project clock without modifying your primary database.
