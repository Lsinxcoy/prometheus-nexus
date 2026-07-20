"""Omega Gateway — 生产级 Docker 部署镜像

构建：docker build -t omega-gateway:latest .
运行：docker run -p 9201:9201 -v omega-data:/app/data omega-gateway:latest
"""
FROM python:3.11-slim

WORKDIR /app

# 系统依赖
RUN apt-get update && \
    apt-get install -y --no-install-recommends curl && \
    rm -rf /var/lib/apt/lists/*

# Python 依赖
COPY requirements-gateway.txt .
RUN pip install --no-cache-dir -r requirements-gateway.txt

# 应用代码
COPY src/ src/
COPY gateway/ gateway/
COPY run_gateway.py .
COPY config_gateway.yaml .

# 数据卷
RUN mkdir -p /app/data
VOLUME ["/app/data"]

# 暴露端口
EXPOSE 9201

# 健康检查
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD curl -f http://localhost:9201/health || exit 1

# 启动
CMD ["python", "run_gateway.py", "--db-path", "/app/data/omega.db"]
