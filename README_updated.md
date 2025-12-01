# YouTube Downloader Service (Updated)

基于 FastAPI 和 yt-dlp 的视频下载服务，支持 Cookie 字符串传递和字幕下载。

## 主要更新

- ✅ Cookie 设置改为传递字符串，不再需要上传文件
- ✅ 成功获取字幕后自动更新 Cookie
- ✅ 提供 Docker 部署方案，支持 Traefik 反向代理

## API 端点

### 1. 获取视频信息
```
GET /info?url=<video_url>&cookie_string=<optional_cookie>
```

### 2. 下载视频和字幕
```
POST /download
```
请求体:
```json
{
    "url": "https://www.youtube.com/watch?v=VIDEO_ID",
    "cookie_string": "# Netscape HTTP Cookie File\n# Optional cookie content...",
    "download_subtitles": true,
    "subtitle_lang": "en",
    "format_quality": "best"
}
```

响应示例:
```json
{
    "status": "success",
    "title": "Video Title",
    "video_file": "/path/to/video.mp4",
    "subtitle_files": ["/path/to/subtitle.vtt"],
    "download_path": "/path/to/download",
    "updated_cookie": "# Updated cookie content...",
    "message": "下载完成！视频: video.mp4, 字幕: 1 个，Cookie已更新"
}
```

### 3. 设置 Cookie
```
POST /cookie/set
```
请求体:
```json
{
    "cookie_name": "youtube_cookies",
    "cookie_content": "# Netscape HTTP Cookie File\n# Your cookie content here..."
}
```

### 4. 列出所有 Cookie
```
GET /cookie/list
```

### 5. 删除 Cookie
```
DELETE /cookie/{cookie_name}
```

## 部署

### 使用 Docker Compose (推荐)

1. 确保已有 Traefik 运行并配置了 `letsencrypt` 证书解析器
2. 创建 Traefik 网络（如果尚未创建）：
   ```bash
   docker network create traefik
   ```
3. 部署服务：
   ```bash
   docker-compose up -d
   ```

服务将在 `https://ytt.subx.fun` 上可用，支持自动 HTTPS 证书。

### 本地开发

```bash
# 安装依赖
uv sync

# 运行服务
uv run python main.py
```

## Cookie 格式

Cookie 应为 Netscape 格式，示例：
```
# Netscape HTTP Cookie File
.youtube.com	TRUE	/	TRUE	1234567890	session_token	your_session_token_here
```

## 功能特点

- 🎥 支持多种视频格式下载
- 📝 自动下载字幕（VTT 格式）
- 🍪 Cookie 字符串传递，无需文件上传
- 🔄 字幕下载成功后自动更新 Cookie
- 🐳 Docker 容器化部署
- 🔒 Traefik + Let's Encrypt 自动 HTTPS
- 🧹 临时文件自动清理

## 环境要求

- Python 3.13+
- FFmpeg (用于视频处理)
- Docker & Docker Compose (用于容器化部署)