# 使用官方Python 3.13镜像
FROM python:3.13-slim

# 设置工作目录
WORKDIR /app

# 安装系统依赖
RUN apt-get update && apt-get install -y \
    ffmpeg \
    && rm -rf /var/lib/apt/lists/*

# 安装uv包管理器
RUN pip install uv

# 1. 优先复制依赖配置文件
COPY pyproject.toml uv.lock README.md ./

# 2. 安装Python依赖 (利用缓存)
# 使用 --no-install-project 避免在缺少源码时报错
RUN uv sync --frozen --no-install-project

# 3. 批量复制所有 Python 文件及相关资源
COPY *.py index.html .env* ./

# 创建必要的目录
RUN mkdir -p /app/downloads /app/cookies

# 暴露端口
EXPOSE 24314

# 启动应用
CMD ["uv", "run", "python", "startup.py"]