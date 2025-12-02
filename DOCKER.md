# Docker Compose 使用说明

本项目使用单一的 `docker-compose.yml` 文件支持本地开发和生产环境，通过 Docker Compose profiles 功能区分。

## 快速开始

### 本地开发环境

使用 `--profile local` 启动本地开发环境：

```bash
docker-compose --profile local up -d
```

本地环境特点：
- 容器名称：`ytbscript-local`
- 端口映射：`24314:24314`
- 使用本地目录挂载（`./downloads` 和 `./cookies`）
- 访问地址：http://localhost:24314

### 生产环境

生产环境使用默认配置（不需要指定 profile）：

1. 确保 Traefik 网络已创建：

```bash
docker network create traefik
```

2. 启动服务：

```bash
docker-compose up -d
```

生产环境特点：
- 容器名称：`ytbscript`
- 通过 Traefik 反向代理访问（不直接暴露端口）
- 使用 Docker 命名卷
- 访问地址：https://ytt.subx.fun（通过 Traefik）

## 常用命令

### 本地开发

```bash
# 启动本地开发环境
docker-compose --profile local up -d

# 查看日志
docker-compose --profile local logs -f

# 停止服务
docker-compose --profile local down

# 重新构建并启动
docker-compose --profile local up -d --build

# 查看服务状态
docker-compose --profile local ps
```

### 生产环境

```bash
# 启动生产环境
docker-compose up -d

# 查看日志
docker-compose logs -f

# 停止服务
docker-compose down

# 重新构建并启动
docker-compose up -d --build

# 查看服务状态
docker-compose ps
```

## 配置文件

所有应用配置（API Token、数据库连接等）都在 `.env` 文件中设置。

复制示例文件并根据需要修改：

```bash
cp .env.example .env
```
