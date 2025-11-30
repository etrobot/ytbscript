# YouTube Downloader Service

基于 FastAPI 和 yt-dlp 的视频下载服务，支持 cookie 管理和字幕下载（VTT 格式）。

## 功能特性

- ✅ 下载 YouTube 视频
- ✅ 支持上传和管理 Cookie 文件
- ✅ 自动下载默认字幕（VTT 格式）
- ✅ 获取视频信息
- ✅ RESTful API 接口
- ✅ 自动清理功能

## 安装依赖

```bash
# 使用 uv（推荐）
uv sync

# 或使用 pip
pip install -e .
```

## 运行服务

```bash
# 使用 uvicorn 直接运行
uvicorn main:app --reload --host 0.0.0.0 --port 8000

# 或直接运行 main.py
python main.py
```

服务将在 `http://localhost:8000` 启动。

## API 文档

启动服务后，访问以下地址查看交互式 API 文档：

- Swagger UI: `http://localhost:8000/docs`
- ReDoc: `http://localhost:8000/redoc`

## API 端点

### 1. 获取视频信息

```bash
GET /info?url=<video_url>&use_cookie=false&cookie_name=cookies.txt
```

**示例：**
```bash
curl "http://localhost:8000/info?url=https://www.youtube.com/watch?v=dQw4w9WgXcQ"
```

### 2. 下载视频和字幕

```bash
POST /download
Content-Type: application/json

{
  "url": "https://www.youtube.com/watch?v=dQw4w9WgXcQ",
  "use_cookie": false,
  "cookie_name": "cookies.txt",
  "download_subtitles": true,
  "subtitle_lang": "en",
  "format_quality": "best"
}
```

**示例：**
```bash
curl -X POST "http://localhost:8000/download" \
  -H "Content-Type: application/json" \
  -d '{
    "url": "https://www.youtube.com/watch?v=dQw4w9WgXcQ",
    "download_subtitles": true,
    "subtitle_lang": "en"
  }'
```

**字幕语言代码：**
- `en` - 英文
- `zh-Hans` - 简体中文
- `zh-Hant` - 繁体中文
- `ja` - 日文
- `ko` - 韩文
- `es` - 西班牙文
- `fr` - 法文

### 3. 上传 Cookie 文件

```bash
POST /cookie/upload
Content-Type: multipart/form-data

file: <cookie_file>
cookie_name: <optional_custom_name>
```

**示例：**
```bash
curl -X POST "http://localhost:8000/cookie/upload" \
  -F "file=@cookies.txt" \
  -F "cookie_name=my_cookies"
```

### 4. 列出所有 Cookie

```bash
GET /cookie/list
```

**示例：**
```bash
curl "http://localhost:8000/cookie/list"
```

### 5. 删除 Cookie

```bash
DELETE /cookie/{cookie_name}
```

**示例：**
```bash
curl -X DELETE "http://localhost:8000/cookie/my_cookies.txt"
```

### 6. 清理下载文件

```bash
DELETE /cleanup
```

**示例：**
```bash
curl -X DELETE "http://localhost:8000/cleanup"
```

## Cookie 文件格式

Cookie 文件需要使用 Netscape 格式（`cookies.txt`）。你可以使用浏览器插件导出：

### Chrome/Edge
- 插件：[Get cookies.txt](https://chrome.google.com/webstore/detail/get-cookiestxt/bgaddhkoddajcdgocldbbfleckgcbcid)

### Firefox
- 插件：[cookies.txt](https://addons.mozilla.org/en-US/firefox/addon/cookies-txt/)

## 使用场景

### 场景 1：下载公开视频和字幕

```bash
curl -X POST "http://localhost:8000/download" \
  -H "Content-Type: application/json" \
  -d '{
    "url": "https://www.youtube.com/watch?v=VIDEO_ID",
    "download_subtitles": true,
    "subtitle_lang": "zh-Hans"
  }'
```

### 场景 2：使用 Cookie 下载会员视频

1. 先上传 cookie：
```bash
curl -X POST "http://localhost:8000/cookie/upload" \
  -F "file=@cookies.txt"
```

2. 下载视频：
```bash
curl -X POST "http://localhost:8000/download" \
  -H "Content-Type: application/json" \
  -d '{
    "url": "https://www.youtube.com/watch?v=VIDEO_ID",
    "use_cookie": true,
    "cookie_name": "cookies.txt",
    "download_subtitles": true,
    "subtitle_lang": "en"
  }'
```

### 场景 3：只下载字幕

修改 yt-dlp 选项，设置 `skip_download: true`（需要修改代码）。

## 目录结构

```
ytbscript/
├── main.py              # FastAPI 应用主文件
├── pyproject.toml       # 项目配置和依赖
├── README.md            # 项目文档
└── .venv/               # 虚拟环境
```

## 临时文件位置

- 下载文件：`/tmp/ytbscript_downloads/`
- Cookie 文件：`/tmp/ytbscript_cookies/`

## 注意事项

1. **Cookie 安全性**：Cookie 文件包含敏感信息，请妥善保管
2. **存储空间**：定期使用 `/cleanup` 端点清理下载文件
3. **版权问题**：请遵守视频平台的服务条款和版权法规
4. **网络限制**：某些地区可能需要代理才能访问 YouTube

## 开发

### 项目依赖

- **FastAPI**: Web 框架
- **Uvicorn**: ASGI 服务器
- **yt-dlp**: 视频下载工具
- **Pydantic**: 数据验证

### 扩展功能

可以添加的功能：
- [ ] 下载进度追踪
- [ ] 异步任务队列
- [ ] 批量下载
- [ ] 视频格式转换
- [ ] 数据库存储下载历史
- [ ] 用户认证

## 许可证

MIT License

## 贡献

欢迎提交 Issue 和 Pull Request！
