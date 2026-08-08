# Problem Statement: ARC Knowledge Graph CLI

## Project Overview
Build ARC, a command-line interface (CLI) tool designed for software developers and hackathon teams to track project goals, architecture, and task dependencies offline.

## Requirements
1. **Core Database Engine**: Implement a SQLite-backed knowledge graph schema in `arc_cli/graph.py` supporting nodes (`type`, `label`, `properties`) and directed edges (`source_id`, `target_id`, `relation`).
2. **Context Ingestion**: Create an `arc ingest` command to read project documents (`problem_statement.md`, `README.md`) and store the concatenated text in an `ingested_context` memory node.
3. **Plan Generation**: Implement an `arc plan` command using a local LLM (offline model) to automatically decompose the ingested context into milestone nodes (`owner`, `deadline_hours`, `status`) and `depends_on` relationship edges.
4. **CLI User Interface**: Use Typer and Rich to display formatted milestone tables, dependencies, and command outputs cleanly.