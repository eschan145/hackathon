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
        # Perf tuning (no change to the model weights themselves):
        # - OLLAMA_CONTEXT_LENGTH: qwen3-vl's native max is 262144, and Ollama
        #   auto-sizes the KV cache to that on this box's large unified memory
        #   unless capped, ballooning the loaded model from 19GB to 45GB and
        #   slowing every load/reload. Our prompts (DSL grammar + condensed
        #   history + screen state, occasionally one screenshot) are a couple
        #   KB, so 32768 leaves generous headroom at a fraction of the memory.
        # - OLLAMA_KV_CACHE_TYPE=q8_0: quantized KV cache, further shrinks the
        #   loaded footprint (down to ~20GB) with no measurable decode-speed
        #   cost at these prompt lengths.
        # - OLLAMA_FLASH_ATTENTION=1: force on rather than leaving it on "auto".
        # - OLLAMA_KEEP_ALIVE=30m: the default 5m unload meant any gap between
        #   agent turns longer than that paid a ~10s reload penalty on the
        #   next call - this is most of what "slow" felt like in practice.
        OLLAMA_CONTEXT_LENGTH=32768 \
        OLLAMA_KV_CACHE_TYPE=q8_0 \
        OLLAMA_FLASH_ATTENTION=1 \
        OLLAMA_KEEP_ALIVE=30m \
        ollama serve >/dev/null 2>&1 &

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

    # Cap the per-call generation length OpenClaw will request from this
    # model (was 8192 tokens; this is a thinking-tagged checkpoint that
    # always emits a hidden reasoning block before its answer, so an
    # unbounded/very-high cap means an occasional turn can ramble for a
    # long time before ever reaching its action lines). 1536 leaves plenty
    # of room for reasoning + a handful of DSL action lines while bounding
    # worst-case tail latency. Idempotent - safe to run on every start.
    openclaw config set 'models.providers.ollama.models[0].maxTokens' 1536 --strict-json >/dev/null 2>&1 || true

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
