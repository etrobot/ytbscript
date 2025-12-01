#!/bin/bash

# YouTube Downloader Service 部署脚本

echo "🚀 开始部署 YouTube Downloader Service..."

# 检查 Docker 是否安装
if ! command -v docker &> /dev/null; then
    echo "❌ Docker 未安装，请先安装 Docker"
    exit 1
fi

# 检查 Docker Compose 是否安装
if ! command -v docker-compose &> /dev/null; then
    echo "❌ Docker Compose 未安装，请先安装 Docker Compose"
    exit 1
fi

# 检查 Traefik 网络是否存在
if ! docker network ls | grep -q "traefik"; then
    echo "📡 创建 Traefik 网络..."
    docker network create traefik
else
    echo "✅ Traefik 网络已存在"
fi

# 构建并启动服务
echo "🔨 构建并启动服务..."
docker-compose up -d --build

# 检查服务状态
sleep 5
if docker-compose ps | grep -q "Up"; then
    echo "✅ 服务启动成功!"
    echo "🌐 服务地址: https://ytt.subx.fun"
    echo "📚 API 文档: https://ytt.subx.fun/docs"
else
    echo "❌ 服务启动失败，请查看日志:"
    docker-compose logs
    exit 1
fi

echo ""
echo "🎉 部署完成！"
echo ""
echo "常用命令："
echo "  查看日志: docker-compose logs -f"
echo "  重启服务: docker-compose restart"
echo "  停止服务: docker-compose down"
echo "  查看状态: docker-compose ps"