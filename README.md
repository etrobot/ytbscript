# YouTube 字幕服务 API

简洁、高效的YouTube字幕下载和管理服务。

## 🚀 核心功能

- **智能缓存**: 自动管理数据库缓存，性能提升10倍以上
- **批量处理**: 支持频道级别的异步批量处理
- **Cookie管理**: 支持Cookie保存和自动使用

---

## 📡 API接口

### 认证

所有API都需要Token认证（除了`/health`）：

```bash
-H "X-API-Token: Abcd123456"
```

---

### 1️⃣ POST `/api/save_cookie`

保存/更新Cookie

**请求**:
```bash
curl -X POST "http://localhost:24314/api/save_cookie" \
  -H "X-API-Token: Abcd123456" \
  -H "Content-Type: application/json" \
  -d '{
    "cookie_name": "youtube_cookies",
    "cookie_content": "Cookie内容"
  }'
```

**响应**:
```json
{
  "status": "success",
  "message": "Cookie已保存: youtube_cookies.txt",
  "path": "/path/to/cookies/youtube_cookies.txt"
}
```

---

### 2️⃣ POST `/api/subtitle`

智能获取视频字幕（优先从数据库，不存在则下载并保存）

**请求**:
```bash
curl -X POST "http://localhost:24314/api/subtitle" \
  -H "X-API-Token: Abcd123456" \
  -H "Content-Type: application/json" \
  -d '{
    "url": "https://www.youtube.com/watch?v=VIDEO_ID",
    "subtitle_lang": "en"
  }'
```

**支持的URL格式**:
- `https://www.youtube.com/watch?v=VIDEO_ID`
- `https://youtu.be/VIDEO_ID`
- `https://www.youtube.com/shorts/VIDEO_ID`

**响应**:

从数据库获取（快速）：
```json
{
  "status": "success",
  "source": "database",
  "video_id": "VIDEO_ID",
  "title": "视频标题",
  "uploader": "上传者",
  "subtitle_count": 60,
  "subtitles": [...]
}
```

从YouTube下载（首次）：
```json
{
  "status": "success",
  "source": "downloaded",
  "video_id": "VIDEO_ID",
  "title": "视频标题",
  "duration": 213,
  "subtitle_count": 60,
  "subtitles": [...]
}
```

**性能对比**:
- 首次请求（下载）：~10秒
- 后续请求（数据库）：<1秒
- **性能提升：10倍以上** 🚀

---

### 3️⃣ POST `/api/channel_task`

启动频道更新任务（异步）

**请求**:
```bash
curl -X POST "http://localhost:24314/api/channel_task" \
  -H "X-API-Token: Abcd123456" \
  -H "Content-Type: application/json" \
  -d '{
    "channel_url": "https://www.youtube.com/@ChannelName",
    "max_videos": 50,
    "subtitle_lang": "en"
  }'
```

**响应**:
```json
{
  "task_id": "uuid-string",
  "status": "running",
  "message": "频道更新任务已启动"
}
```

---

### 3.1 GET `/api/channel_task/{task_id}`

查询频道任务状态

**请求**:
```bash
curl -X GET "http://localhost:24314/api/channel_task/{task_id}" \
  -H "X-API-Token: Abcd123456"
```

**响应**:
```json
{
  "task_id": "uuid-string",
  "status": "running",
  "progress": 50,
  "total_items": 100,
  "current_item": "正在处理: 视频标题",
  "created_at": "2025-12-09 22:00:00",
  "result": null
}
```

任务完成后，`result`字段会包含处理结果。

---

## 📖 使用示例

### Python

```python
import requests

API_URL = "http://localhost:24314"
TOKEN = "Abcd123456"
headers = {"X-API-Token": TOKEN, "Content-Type": "application/json"}

# 1. 获取字幕
response = requests.post(
    f"{API_URL}/api/subtitle",
    json={
        "url": "https://www.youtube.com/watch?v=dQw4w9WgXcQ",
        "subtitle_lang": "en"
    },
    headers=headers
)
data = response.json()
print(f"数据源: {data['source']}")  # database 或 downloaded
print(f"字幕数: {data['subtitle_count']}")

# 2. 启动频道任务
task_response = requests.post(
    f"{API_URL}/api/channel_task",
    json={
        "channel_url": "https://www.youtube.com/@channel",
        "max_videos": 50,
        "subtitle_lang": "en"
    },
    headers=headers
)
task_id = task_response.json()["task_id"]

# 3. 查询任务状态
status_response = requests.get(
    f"{API_URL}/api/channel_task/{task_id}",
    headers=headers
)
print(f"任务状态: {status_response.json()['status']}")
```

### JavaScript

```javascript
const API_URL = "http://localhost:24314";
const TOKEN = "Abcd123456";

// 获取字幕
async function getSubtitle(videoUrl) {
  const response = await fetch(`${API_URL}/api/subtitle`, {
    method: 'POST',
    headers: {
      'X-API-Token': TOKEN,
      'Content-Type': 'application/json'
    },
    body: JSON.stringify({
      url: videoUrl,
      subtitle_lang: 'en'
    })
  });
  
  const data = await response.json();
  console.log(`数据源: ${data.source}`);
  return data;
}

// 启动频道任务
async function startChannelTask(channelUrl) {
  const response = await fetch(`${API_URL}/api/channel_task`, {
    method: 'POST',
    headers: {
      'X-API-Token': TOKEN,
      'Content-Type': 'application/json'
    },
    body: JSON.stringify({
      channel_url: channelUrl,
      max_videos: 50,
      subtitle_lang: 'en'
    })
  });
  
  const data = await response.json();
  return data.task_id;
}
```

---

## 🔧 配置

### 环境变量

在`.env`文件中配置：

```bash
API_TOKEN=Abcd123456
API_TOKEN_HEADER=X-API-Token
```

### Cookie管理

1. 先通过`/api/save_cookie`保存Cookie
2. 后续请求会自动使用`cookies/cookies.txt`
3. 也可以在请求中传入`cookie`参数临时使用

---

## 🎯 使用场景

### 场景1: 查询单个视频

```bash
curl -X POST "http://localhost:24314/api/subtitle" \
  -H "X-API-Token: Abcd123456" \
  -H "Content-Type: application/json" \
  -d '{"url": "https://youtu.be/VIDEO_ID", "subtitle_lang": "en"}'
```

优势：
- 首次自动下载并缓存
- 后续极快（<1秒）
- 自动管理

### 场景2: 批量处理频道

```bash
# 启动任务
TASK_ID=$(curl -s -X POST "http://localhost:24314/api/channel_task" \
  -H "X-API-Token: Abcd123456" \
  -H "Content-Type: application/json" \
  -d '{
    "channel_url": "https://www.youtube.com/@channel",
    "max_videos": 100,
    "subtitle_lang": "en"
  }' | jq -r '.task_id')

# 查询状态
curl -X GET "http://localhost:24314/api/channel_task/$TASK_ID" \
  -H "X-API-Token: Abcd123456"
```

### 场景3: 持续集成

```python
# 定期更新频道
import time

def update_channel_continuously(channel_url):
    # 启动任务
    task_id = start_channel_task(channel_url)
    
    # 轮询状态
    while True:
        status = get_task_status(task_id)
        if status['status'] in ['completed', 'failed']:
            break
        time.sleep(10)
    
    print(f"任务完成: {status['result']}")
```

---

## 📊 性能指标

| 操作 | 首次 | 后续 | 提升 |
|------|------|------|------|
| 单个视频 | ~10秒 | <1秒 | 10倍+ |
| 50个视频 | ~2分钟 | N/A | N/A |

---

## ❌ 错误处理

| 状态码 | 说明 | 解决方法 |
|--------|------|----------|
| 200 | 成功 | - |
| 400 | 无效请求 | 检查URL格式 |
| 401 | 认证失败 | 检查Token |
| 404 | 未找到 | 视频可能无字幕 |
| 500 | 服务器错误 | 查看详细错误信息 |

---

## 📈 版本历史

### v3.0 (当前版本)
- ✅ 简化为3个核心API
- ✅ 统一路径前缀`/api/*`
- ✅ 清晰的命名规范
- ✅ 代码精简至455行

### v2.0
- 合并重复端点
- 智能缓存机制
- 异步任务支持

### v1.0
- 基础字幕下载功能
- 批量处理支持

---

## 🎉 总结

**3个核心API，清晰简洁：**

1. `/api/save_cookie` - 保存Cookie
2. `/api/subtitle` - 智能获取字幕
3. `/api/channel_task` - 频道任务

**设计原则：**
- ✅ RESTful风格
- ✅ 命名清晰
- ✅ 功能明确
- ✅ 易于使用

**代码质量：**
- 总行数: 455行
- 核心API: 3个
- 代码精简、易维护
