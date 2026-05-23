# Quick Start

A privacy-first AI accountant for Australian small businesses. All data and models run locally — nothing leaves your machine.

## Prerequisites

- [Docker Desktop](https://www.docker.com/products/docker-desktop/) (or Docker Engine in WSL)
- ~5 GB free disk space (for Ollama models)
- NVIDIA GPU recommended (CPU works but is slower)

## Start with Docker (recommended)

```bash
git clone <repo-url>
cd privacy_first_accountant

docker compose up --build
```

On first run, Docker will automatically pull the required AI models (`llama3.2:3b` and `nomic-embed-text`). This takes a few minutes.

Once running:

| Service  | URL                       |
| -------- | ------------------------- |
| Frontend | http://localhost:3000     |
| Backend  | http://localhost:8000     |
| Ollama   | http://localhost:11434    |

## Start without Docker (local dev)

Requirements: Python 3.10+, Node.js 18+, [Ollama](https://ollama.com/download)

```bash
# Pull models
ollama pull llama3.2:3b
ollama pull nomic-embed-text

# Backend
python -m venv .venv && source .venv/bin/activate
pip install -r backend/requirements.txt
uvicorn backend.main:app --reload --port 8000

# Frontend (separate terminal)
cd frontend
npm install
npm run dev
```

Or use the helper script:

```bash
bash start.sh
```

## Data

All data is stored in `./data/`:

- `./data/accountant.db` — SQLite transaction database
- `./data/chroma_db/` — vector embeddings

To view the database, open `accountant.db` in VS Code with the **SQLite Viewer** extension.

## Stop

```bash
docker compose down
```

To also delete all model data:

```bash
docker compose down -v
```
