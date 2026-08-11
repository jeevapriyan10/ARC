# ARC CLI — Autonomous Reasoning & Intervention Engine

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![Python Version](https://img.shields.io/badge/python-3.9%2B-blue.svg)](https://www.python.org/downloads/)
[![CLI Framework](https://img.shields.io/badge/CLI-Typer-009485.svg)](https://typer.tiangolo.com/)
[![Formatting](https://img.shields.io/badge/UI-Rich-magenta.svg)](https://rich.readthedocs.io/)

**ARC** (Autonomous Reasoning CLI) is a lightweight, offline-first Knowledge Graph engine designed to eliminate project drift, track milestone progress, and automate developer interventions in fast-paced software projects and hackathons.

---

## Key Features

- **Offline Knowledge Graph**: Built on SQLite (`.arc/arc.db`), modeling milestones, git commits, risk signals, gate decisions, and context memory.
- **Git Post-Commit Integration**: `arc watch` automatically links modified files to target milestone tasks upon git commits.
- **Drift & Inactivity Heartbeat**: Detects overdue deadlines and commit silence on critical-path milestones.
- **3-Rule Intervention Gate**: Prevents notification spam by filtering risk signals through **Materiality**, **Timing**, and **Specificity** checks.
- **Local AI Synthesis**: Integrates with local Ollama or Hugging Face models (with offline fallback) for generating milestone plans, drafting tailored Slack nudges, and outputting pitch-readiness reports (`.arc/report.md`).
- **Time-Aware Replay Mode**: Replays scripted project timelines using a virtual project clock for live presentations (`arc demo`).

---

## Architecture Overview

```mermaid
graph TD
    Ingest["Context Ingestion (arc ingest)"] --> MemoryNode["Memory Node"]
    MemoryNode --> Plan["Local LLM Planner (arc plan)"]
    Plan --> Milestones["Milestone Nodes & Dependencies"]
    
    GitHook["Git Post-Commit Hook (arc watch)"] --> CommitNode["Commit Node"]
    CommitNode -- touches --> Milestones
    
    Milestones -- causes --> Risks["Drift / Inactivity Risk Nodes"]
    Risks --> Gate Engine
    
    subgraph Gate Engine ["3-Rule Intervention Gate"]
        Mat["1. Materiality Check"]
        Tim["2. Timing Window (4h)"]
        Spec["3. Specificity Check"]
    end
    
    Gate Engine -- FIRE NUDGE --> Slack["Slack Alert / Nudge Log"]
    Gate Engine -- STAY SILENT --> Silent["Suppress Notification"]
    
    Milestones --> Report["Pitch Readiness Report (arc report)"]
```

### Knowledge Graph Schema

- **Nodes**: `milestone`, `commit`, `risk`, `decision`, `nudge`, `memory`
- **Edges**:
  - `depends_on`: Connects dependent milestones (`Milestone B --depends_on--> Milestone A`)
  - `touches`: Connects commits to milestones (`Commit C --touches--> Milestone A`)
  - `causes`: Connects overdue milestones to risks (`Milestone A --causes--> Risk R`)
  - `links_to`: Connects gate decisions to dispatched nudges (`Decision D --links_to--> Nudge N`)

---

## Quickstart

### Prerequisites
- Python 3.9+
- Git

### Installation

Clone the repository and install locally in editable mode:

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

## Typical Developer Workflow

### 1. Initialize & Ingest Project Context
```bash
arc init
arc ingest problem_statement.md README.md
```

### 2. Generate Milestone Plan
```bash
arc plan
```

### 3. Enable Git Hook Monitoring
```bash
arc watch
```

### 4. Check Project Status & Drift Signals
```bash
arc status
```

### 5. Generate Pitch Readiness & Executive Summary
```bash
arc report
```
Generates `.arc/report.md` containing a Pitch-Readiness Summary, Blocker Digest, and Pitch Outline.

---

## Command Reference

| Command | Arguments / Options | Description |
|---|---|---|
| `arc init` | None | Initializes `.arc/arc.db` Knowledge Graph database schema. |
| `arc ingest` | `<files...>` | Reads doc files into graph memory for milestone planning. |
| `arc plan` | `[--model -m]` | Uses local LLM to generate milestone nodes & dependency edges. |
| `arc watch` | None | Installs `.git/hooks/post-commit` for auto commit-tracking. |
| `arc status` | `[--silence-hours -s 4.0]` | Evaluates deadlines, commit silence, and gate decisions. |
| `arc report` | `[--model -m]` | Synthesizes project status into `.arc/report.md`. |
| `arc demo` | `<script.json> [--delay -d 1.5]` | Replays a simulated timeline with a virtual project clock. |

---

## Demo Replay Mode

To showcase ARC's judgment loop in a live presentation:

```bash
arc demo demo_scenario.json --delay 0.5
```

This runs through a simulated project timeline without touching your real project database.

---

## Running Tests

Run the unit test suite using `pytest`:

```bash
python -m pytest -v
```

---

## Contributing

Contributions are welcome! Please read our [Contributing Guidelines](CONTRIBUTING.md) for details on submitting pull requests and reporting issues.

---

## License

This project is licensed under the [MIT License](LICENSE).
