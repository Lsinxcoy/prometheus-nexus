# Prometheus Ultra Gateway — Makefile
# 用法：make <target>

SHELL := /bin/bash
PYTHON := python3
GATEWAY_DIR := gateway
PORT ?= 9201
HOST ?= 127.0.0.1
DB_PATH ?= omega.db

.PHONY: help run dev test health clean docker-build docker-run docker-stop lint

help: ## 显示帮助
	@grep -E '^[a-zA-Z_-]+:.*##' $(MAKEFILE_LIST) | awk 'BEGIN {FS = ":.*## "}; {printf "\033[36m%-20s\033[0m %s\n", $$1, $$2}'

run: ## 启动 Gateway (生产模式)
	@echo "Starting Omega Gateway on $(HOST):$(PORT)..."
	$(PYTHON) run_gateway.py --host $(HOST) --port $(PORT) --db-path $(DB_PATH)

dev: ## 启动 Gateway (开发模式，热重载)
	@echo "Starting Omega Gateway in dev mode..."
	$(PYTHON) -m uvicorn gateway.gateway:app --factory --reload --host $(HOST) --port $(PORT)

test: ## 运行测试
	@echo "Running tests..."
	$(PYTHON) -m pytest tests/test_gateway.py -v --tb=short

health: ## 健康检查
	@curl -s http://$(HOST):$(PORT)/health | $(PYTHON) -m json.tool 2>/dev/null || echo "Gateway not running"

clean: ## 清理数据库和缓存
	@echo "Cleaning up..."
	rm -f $(DB_PATH)
	rm -rf __pycache__ gateway/__pycache__ src/__pycache__
	find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true
	find . -type d -name '*.egg-info' -exec rm -rf {} + 2>/dev/null || true
	@echo "Done."

docker-build: ## 构建 Docker 镜像
	@echo "Building Docker image..."
	docker build -t omega-gateway:latest .

docker-run: ## 运行 Docker 容器
	docker-compose up -d

docker-stop: ## 停止 Docker 容器
	docker-compose down

docker-logs: ## 查看 Docker 日志
	docker-compose logs -f

lint: ## 代码检查
	@echo "Running linter..."
	$(PYTHON) -m py_compile gateway/response.py
	$(PYTHON) -m py_compile gateway/config.py
	$(PYTHON) -m py_compile gateway/facade.py
	$(PYTHON) -m py_compile gateway/gateway.py
	$(PYTHON) -m py_compile gateway/client.py
	@echo "Lint passed."

install: ## 安装依赖
	@echo "Installing dependencies..."
	pip install -r requirements-gateway.txt
