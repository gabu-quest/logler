#!/bin/bash
set -e

echo "🚀 Starting Logler Stack..."

# Start Rust backend
echo "📦 Starting Rust backend on port 3000..."
cargo build --release --bin logler-server
RUST_LOG=info ./target/release/logler-server &
RUST_PID=$!
echo "✓ Rust backend started (PID: $RUST_PID)"

# Wait for backend to be ready
sleep 2

# Start FastAPI frontend
echo "🌐 Starting FastAPI frontend on port 8000..."
cd backend

if [ ! -d "venv" ]; then
    echo "Creating virtual environment..."
    python3 -m venv venv
fi

source venv/bin/activate
pip install -q -r requirements.txt

python -m uvicorn app.main:app --host 0.0.0.0 --port 8000 &
PYTHON_PID=$!
cd ..

echo "✓ FastAPI frontend started (PID: $PYTHON_PID)"

echo ""
echo "✅ Logler is running!"
echo "   🦀 Rust backend:  http://localhost:3000"
echo "   🐍 Web interface: http://localhost:8000"
echo ""
echo "Press Ctrl+C to stop all services..."

# Trap Ctrl+C and kill both processes
trap "echo '🛑 Stopping services...'; kill $RUST_PID $PYTHON_PID 2>/dev/null; exit" INT

# Wait for either process to exit
wait $RUST_PID $PYTHON_PID
