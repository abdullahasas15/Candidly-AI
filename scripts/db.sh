#!/usr/bin/env bash
# ==============================================================================
# Candidly AI - On-Demand PostgreSQL Controller
# Usage:
#   ./scripts/db.sh start   - Starts PostgreSQL when you want to run the project
#   ./scripts/db.sh stop    - Stops PostgreSQL when you are done working
#   ./scripts/db.sh status  - Checks whether PostgreSQL is running or stopped
# ==============================================================================

set -e

PLIST="/Library/LaunchDaemons/postgresql-18.plist"
BIN="/Library/PostgreSQL/18/bin/pg_isready"

run_admin() {
    local cmd="$1"
    if [ "$EUID" -eq 0 ]; then
        eval "$cmd"
    else
        # Use macOS native prompt for authorization
        osascript -e "do shell script \"$cmd\" with administrator privileges"
    fi
}

is_running() {
    if [ -x "$BIN" ]; then
        "$BIN" -p 5432 >/dev/null 2>&1
        return $?
    fi
    lsof -i :5432 >/dev/null 2>&1
    return $?
}

case "$1" in
    start)
        if is_running; then
            echo "✅ PostgreSQL 18 is already running on port 5432."
            exit 0
        fi
        echo "🚀 Starting PostgreSQL 18 on demand..."
        run_admin "launchctl load -F $PLIST"
        
        # Wait up to 5 seconds for PostgreSQL to accept connections
        for i in {1..10}; do
            if is_running; then
                echo "✅ PostgreSQL 18 started successfully (localhost:5432). Ready for Candidly!"
                exit 0
            fi
            sleep 0.5
        done
        echo "⚠️ PostgreSQL command sent, checking status..."
        ;;
    stop)
        if ! is_running; then
            echo "🛑 PostgreSQL is already stopped."
            exit 0
        fi
        echo "🛑 Stopping PostgreSQL 18..."
        run_admin "launchctl unload -w $PLIST"
        
        for i in {1..10}; do
            if ! is_running; then
                echo "✅ PostgreSQL 18 has been stopped completely. No background processes running."
                exit 0
            fi
            sleep 0.5
        done
        ;;
    status)
        if is_running; then
            echo "🟢 PostgreSQL 18 is RUNNING on port 5432."
        else
            echo "⚪ PostgreSQL 18 is STOPPED (not running in background)."
        fi
        ;;
    *)
        echo "Usage: $0 {start|stop|status}"
        echo ""
        echo "  ./scripts/db.sh start   - Start PostgreSQL when needed"
        echo "  ./scripts/db.sh stop    - Stop PostgreSQL when done"
        echo "  ./scripts/db.sh status  - Check status"
        exit 1
        ;;
esac
