---
trigger: always_on
---

Always refer to 'instructions.md' and 'details.md' for information about the project.

Run command to start a server:
python -m uvicorn local.app:app --reload --port 8000

Run command to start the client:
python games/rps_client.py --port 8000