### Project Overview

This project is a Python-based backend framework called "pyslap" designed for creating scalable, serverless-friendly, and stateless multiplayer games. It uses a modular architecture that separates the core game engine from game-specific logic and infrastructure implementations. The framework is built with FastAPI for the API layer and is designed to be database-agnostic.

**Key Technologies:**

*   **Backend Framework:** FastAPI
*   **Core Logic:** Python
*   **Database:** Database-agnostic, with a local implementation using SQLite.
*   **Testing:** pytest

### Building and Running

**1. Install Dependencies:**

The project uses `uv` for package management. To install dependencies, run:

```bash
uv pip install -r requirements.txt
```

**2. Set Environment Variables:**

The application requires the following environment variables to be set:

```bash
export PYSLAP_SECRET_KEY='your-secret-key'
export PYSLAP_EXTERNAL_SECRET='your-external-secret'
```

**3. Run the Local Server:**

To run the local development server, use `uvicorn`:

```bash
.venv\Scripts\python -m uvicorn local.app:app --reload
```

**4. Running Tests:**

Tests are run using `pytest`:

```bash
python -m pytest tests/
```

### Development Conventions

*   **Modular Architecture:** The framework enforces a separation of concerns between the core engine, game rules, and infrastructure interfaces.
*   **Stateless Design:** The core engine is designed to be stateless, relying on a database for state persistence. This makes it suitable for serverless deployments.
*   **Type Hinting:** The codebase uses Python's type hinting for better code clarity and validation.
*   **Testing:** The project has a dedicated `tests` directory and uses `pytest` for unit and integration testing.
*   **Code Style:** Follows PEP 8 guidelines for Python code style, except add a space after method name declaration and before the opening parenthesis.
