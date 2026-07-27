#!/bin/bash
set -e

# Get the script directory
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

# Color codes
RED='\033[0;31m'
GREEN='\033[0;32m'
BLUE='\033[0;34m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# Lock file for single instance
LOCK_FILE="/tmp/hackathon-assistant.lock"

# Cleanup function
cleanup() {
    echo -e "\n${YELLOW}🛑 Shutting down services...${NC}"

    # Kill all background processes
    jobs -p | xargs -r kill 2>/dev/null || true

    # Wait a moment for processes to die
    sleep 1

    # Force kill any remaining processes on our ports
    fuser -k 11434/tcp 2>/dev/null || true  # Ollama (if was running)
    fuser -k 5173/tcp 2>/dev/null || true   # Frontend

    # Remove lock file
    rm -f "$LOCK_FILE"

    echo -e "${GREEN}✓ Services stopped${NC}"
    exit 0
}

# Check if already running
check_existing_instance() {
    if [ -f "$LOCK_FILE" ]; then
        local old_pid=$(cat "$LOCK_FILE")
        if kill -0 "$old_pid" 2>/dev/null; then
            echo -e "${YELLOW}⚠️  Hackathon Assistant is already running (PID: $old_pid)${NC}"
            echo -e "${YELLOW}Stopping existing instance...${NC}"
            kill "$old_pid" 2>/dev/null || true
            sleep 2
        fi
    fi

    # Kill any lingering processes
    killall node 2>/dev/null || true
    killall ollama 2>/dev/null || true
    pkill -f "uvicorn backend.main" 2>/dev/null || true

    # Force release ports
    fuser -k 11434/tcp 2>/dev/null || true
    fuser -k 8765/tcp 2>/dev/null || true
    fuser -k 5173/tcp 2>/dev/null || true

    sleep 1

    # Write our PID to lock file
    echo $$ > "$LOCK_FILE"
}

# Start Ollama (serving Qwen3-VL) and register it with OpenClaw
setup_local_models() {
    if ! command -v ollama &> /dev/null; then
        echo -e "${RED}❌ ollama not found on PATH. Install it from https://ollama.com${NC}"
        return 1
    fi

    echo -e "${BLUE}📦 Starting local Ollama model server...${NC}"

    if ! curl -s http://localhost:11434/api/version >/dev/null 2>&1; then
        echo -e "${GREEN}▶ Starting Ollama daemon...${NC}"
        # Keep the model resident indefinitely once loaded - the default
        # ~5min idle unload means the first request after any pause pays a
        # full cold-load of a ~45GB model again, which dwarfs normal
        # per-turn latency.
        OLLAMA_KEEP_ALIVE=-1 ollama serve >/dev/null 2>&1 &

        local retry_count=0
        while ! curl -s http://localhost:11434/api/version >/dev/null 2>&1; do
            sleep 1
            retry_count=$((retry_count + 1))
            if [ $retry_count -gt 30 ]; then
                echo -e "${RED}❌ Ollama daemon failed to start${NC}"
                return 1
            fi
        done
    fi
    echo -e "${GREEN}✓ Ollama daemon running${NC}"

    # Pull the model if it isn't already present locally
    if ! ollama list 2>/dev/null | grep -q "qwen3-vl:30b-a3b"; then
        echo -e "${GREEN}▶ Pulling qwen3-vl:30b-a3b (~19GB, one-time)...${NC}"
        ollama pull qwen3-vl:30b-a3b
    fi
    echo -e "${GREEN}✓ qwen3-vl:30b-a3b available${NC}"

    # Register the Ollama provider with OpenClaw (native integration, no
    # custom base-url plumbing needed)
    echo -e "${GREEN}▶ Registering model with OpenClaw...${NC}"
    if ! openclaw models list --json 2>/dev/null | grep -q "ollama/qwen3-vl:30b-a3b"; then
        openclaw onboard --auth-choice ollama --non-interactive --accept-risk 2>/dev/null || true
    fi

    echo -e "${GREEN}✓ Local model configured${NC}"
}

# Set up trap to catch SIGINT and SIGTERM
trap cleanup SIGINT SIGTERM

# Check if installation is complete
if [ ! -d "venv" ]; then
    echo -e "${RED}❌ Python virtual environment not found${NC}"
    echo "Run './install.sh' first to install dependencies"
    exit 1
fi

if [ ! -d "frontend/node_modules" ]; then
    echo -e "${RED}❌ Node.js dependencies not found${NC}"
    echo "Run './install.sh' first to install dependencies"
    exit 1
fi

echo -e "${BLUE}🚀 Starting Hackathon Assistant${NC}"
echo ""

# Check for existing instances and clean up ports
check_existing_instance

# Activate Python virtual environment
source venv/bin/activate

# Set up local models before starting services
setup_local_models

# Start backend server
echo -e "${GREEN}▶ Starting backend server on http://127.0.0.1:8765${NC}"
python3 -m uvicorn backend.main:app --reload --host 127.0.0.1 --port 8765 2>&1 &
BACKEND_PID=$!
sleep 3

# Check if backend started successfully
if ! kill -0 $BACKEND_PID 2>/dev/null; then
    echo -e "${RED}❌ Failed to start backend server${NC}"
    echo -e "${YELLOW}Trying to free port 8765...${NC}"
    fuser -k 8765/tcp 2>/dev/null || true
    sleep 1
    python3 -m uvicorn backend.main:app --reload --host 127.0.0.1 --port 8765 2>&1 &
    BACKEND_PID=$!
    sleep 3
    if ! kill -0 $BACKEND_PID 2>/dev/null; then
        echo -e "${RED}❌ Failed to start backend server${NC}"
        exit 1
    fi
fi

# Start frontend
echo -e "${GREEN}▶ Starting frontend (Electron dev server on http://127.0.0.1:5173)${NC}"
cd frontend
npm run dev 2>&1 &
FRONTEND_PID=$!
cd ..
sleep 3

# Check if frontend started successfully
if ! kill -0 $FRONTEND_PID 2>/dev/null; then
    echo -e "${RED}❌ Failed to start frontend${NC}"
    kill $BACKEND_PID 2>/dev/null || true
    exit 1
fi

echo ""
echo -e "${GREEN}✓ All services started successfully!${NC}"
echo ""
echo -e "${BLUE}📊 Services running:${NC}"
echo -e "  Backend API: ${BLUE}http://127.0.0.1:8765${NC}"
echo -e "  Frontend Dev: ${BLUE}http://127.0.0.1:5173${NC}"
echo -e "  Electron App: Starting..."
echo ""
echo -e "${YELLOW}Press Ctrl+C to stop all services${NC}"
echo ""

# Wait for background processes
wait
