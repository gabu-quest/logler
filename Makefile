.PHONY: help build build-dev test check fmt lint clean

help: ## Show this help message
	@echo "logler: the Rust crates"
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
	@find . -type d -name "__pycache__" -exec rm -rf {} +
