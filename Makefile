.PHONY: help build test clean run dev docker-build docker-up docker-down install

help: ## Show this help message
	@echo "Logler - Advanced Log Viewer"
	@echo ""
	@echo "Usage: make [target]"
	@echo ""
	@echo "Targets:"
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | sort | awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-15s\033[0m %s\n", $$1, $$2}'

build: ## Build all Rust components (release mode)
	@echo "🔨 Building Rust components..."
	@cargo build --release --all

build-dev: ## Build all Rust components (debug mode)
	@echo "🔨 Building Rust components (debug)..."
	@cargo build --all

test: ## Run all tests
	@echo "🧪 Running tests..."
	@cargo test --all

check: ## Check code without building
	@echo "✓ Checking code..."
	@cargo check --all

fmt: ## Format code
	@echo "🎨 Formatting code..."
	@cargo fmt --all

lint: ## Run linter
	@echo "🔍 Running clippy..."
	@cargo clippy --all --all-targets -- -D warnings

clean: ## Clean build artifacts
	@echo "🧹 Cleaning..."
	@cargo clean
	@rm -rf backend/venv
	@rm -rf backend/__pycache__
	@find . -type d -name "__pycache__" -exec rm -rf {} +

run: ## Start all services (Rust backend + FastAPI frontend)
	@./start.sh

run-backend: ## Run only the Rust backend
	@echo "🦀 Starting Rust backend..."
	@RUST_LOG=info cargo run --release --bin logler-server

run-frontend: ## Run only the FastAPI frontend
	@echo "🐍 Starting FastAPI frontend..."
	@cd backend && python -m uvicorn app.main:app --reload --port 8000

dev: ## Run in development mode with hot reload
	@echo "🔥 Starting in development mode..."
	@make -j2 run-backend run-frontend

docker-build: ## Build Docker images
	@echo "🐳 Building Docker images..."
	@docker-compose build

docker-up: ## Start services with Docker Compose
	@echo "🐳 Starting services..."
	@docker-compose up -d

docker-down: ## Stop Docker services
	@echo "🐳 Stopping services..."
	@docker-compose down

docker-logs: ## View Docker logs
	@docker-compose logs -f

install: ## Install Rust binaries to ~/.cargo/bin
	@echo "📦 Installing logler..."
	@cargo install --path logler-cli
	@cargo install --path logler-server
	@echo "✅ Installed to ~/.cargo/bin"

install-frontend: ## Install Python dependencies
	@echo "📦 Installing Python dependencies..."
	@cd backend && pip install -r requirements.txt

setup: build install-frontend ## Initial setup (build + install dependencies)
	@echo "✅ Setup complete!"
	@echo ""
	@echo "Quick start:"
	@echo "  make run     # Start all services"
	@echo "  make dev     # Start in development mode"
	@echo ""

example: ## Run with example log file
	@echo "📝 Running with example log..."
	@cargo run --bin logler -- view examples/sample.log

build-tailwind: ## Build bundled Tailwind CSS for the web UI
	@npx tailwindcss@3.4.13 -i src/logler/web/static/css/tailwind.input.css -o src/logler/web/static/css/tailwind.css --minify --config src/logler/web/tailwind.config.cjs
