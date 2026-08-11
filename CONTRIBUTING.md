# Contributing to ARC CLI

Thank you for your interest in contributing to ARC CLI! We welcome contributions from developers of all skill levels.

---

## Code of Conduct

Please foster an open, welcoming, and collaborative community. Treat fellow contributors with respect.

---

## How to Contribute

### 1. Reporting Issues or Requesting Features
- Open an issue on GitHub describing the bug or feature request.
- Provide clear steps to reproduce bugs, including OS details and CLI output snapshots.

### 2. Setting Up Your Local Environment

```bash
# Fork & clone the repository
git clone https://github.com/your-username/ARC.git
cd ARC

# Create a virtual environment
python -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate

# Install in editable mode with development dependencies
pip install -e .
pip install pytest
```

### 3. Development & Testing Workflow

1. Create a feature branch:
   ```bash
   git checkout -b feature/my-new-feature
   ```
2. Make your code changes in `arc_cli/`.
3. Add unit tests under `tests/` covering your changes.
4. Run the full pytest test suite:
   ```bash
   python -m pytest -v
   ```
5. Ensure all existing commands and error cases execute cleanly without tracebacks.

### 4. Submitting a Pull Request

- Commit your changes with concise, descriptive commit messages.
- Push your branch to GitHub and open a Pull Request targeting `main`.
- Describe the motivation, architectural impact, and test coverage in your PR description.

---

## License

By contributing to ARC CLI, you agree that your contributions will be licensed under the [MIT License](LICENSE).
