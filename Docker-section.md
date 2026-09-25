## Docker

APEX can be deployed as a Docker container for easy deployment.

### Quick Start

```bash
# Build the image
docker compose build

# Start the platform
docker compose up -d

# Open the dashboard
# http://localhost:8080
```

### Using the CLI

```bash
# Build, start, stop, and view logs
apex docker build
apex docker up
apex docker down
apex docker logs
```

### Persistence

Data is persisted in Docker volumes:
- apex-data — SQLite database (mastery scores, attempt history)
- apex-sessions — Learner session data
- ./content — Exercises and skills (hot-reloadable)

### Configuration

Environment variables:
| Variable | Default | Description |
|---|---|---|
| APEX_DB | /data/apex.db | SQLite database path |
| APEX_CONTENT_DIR | /app/content | Content directory |
| APEX_TIMEOUT_S | 30 | Code execution timeout |
| APEX_MEMORY_MB | 256 | Memory limit for code execution |
| HERMES_TTS_AVAILABLE | 0 | Enable text-to-speech |
