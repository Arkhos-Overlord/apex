#!/bin/bash
set -e

echo "Starting APEX Education Platform..."

# Wait for SQLite database to be ready
if [ ! -f "/data/apex.db" ]; then
    echo "Initializing database..."
    python -c "from apex.store import Store; Store('/data/apex.db')" 2>/dev/null || true
fi

# Start the dashboard API server
echo "Launching dashboard on port 8080..."
exec uvicorn dashboard.server:app --host 0.0.0.0 --port 8080 --reload
