# 使用官方Python 3.13镜像
FROM python:3.13-slim

# 设置工作目录
WORKDIR /app

# 安装系统依赖
RUN apt-get update && apt-get install -y \
    ffmpeg \
    && rm -rf /var/lib/apt/lists/*

# 复制项目文件
COPY pyproject.toml .
COPY uv.lock .
COPY main.py .
COPY subtitle_utils.py .
COPY task_manager.py .
COPY youtube_channel_processor.py .
COPY startup.py .
COPY .env* .

# 安装uv包管理器
RUN pip install uv

# 安装Python依赖
RUN uv sync --frozen

# 创建必要的目录
RUN mkdir -p /app/downloads /app/cookies

# 暴露端口
EXPOSE 24314

# 启动应用
CMD ["uv", "run", "python", "main.py"]