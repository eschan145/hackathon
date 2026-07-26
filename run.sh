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

# Cleanup function
cleanup() {
    echo -e "\n${YELLOW}🛑 Shutting down services...${NC}"

    # Kill all background processes
    jobs -p | xargs -r kill 2>/dev/null || true

    echo -e "${GREEN}✓ Services stopped${NC}"
    exit 0
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

# Activate Python virtual environment
source venv/bin/activate

# Start backend server
echo -e "${GREEN}▶ Starting backend server on http://127.0.0.1:8000${NC}"
python3 -m uvicorn backend.main:app --reload --host 127.0.0.1 --port 8000 2>&1 &
BACKEND_PID=$!
sleep 2

# Check if backend started successfully
if ! kill -0 $BACKEND_PID 2>/dev/null; then
    echo -e "${RED}❌ Failed to start backend server${NC}"
    exit 1
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
echo -e "  Backend API: ${BLUE}http://127.0.0.1:8000${NC}"
echo -e "  Frontend Dev: ${BLUE}http://127.0.0.1:5173${NC}"
echo -e "  Electron App: Starting..."
echo ""
echo -e "${YELLOW}Press Ctrl+C to stop all services${NC}"
echo ""

# Wait for background processes
wait
