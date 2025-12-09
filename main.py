from fastapi import FastAPI, HTTPException, Depends, Header, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from fastapi.responses import HTMLResponse
from pydantic import BaseModel, HttpUrl
from typing import Optional, Dict
from contextlib import asynccontextmanager
import yt_dlp
import shutil
from pathlib import Path
import re
import tempfile
import asyncio
from datetime import datetime
from subtitle_utils import vtt_to_json
from cookie_utils import save_cookie_string_as_netscape, cookie_string_to_netscape
import os
from dotenv import load_dotenv

# 加载环境变量
load_dotenv()

# Token 配置
API_TOKEN = os.getenv("API_TOKEN", "Abcd123456")
TOKEN_HEADER = os.getenv("API_TOKEN_HEADER", "X-API-Token")
TOKEN_PREFIX = os.getenv("TOKEN_PREFIX", "")


@asynccontextmanager
async def app_lifespan(app: FastAPI):
    """统一的生命周期管理，替代 on_event"""
    from youtube_channel_processor import get_processor
    from task_manager import get_task_manager

    processor = get_processor()
    print("✅ YouTube频道处理器已初始化")
    print("✅ 数据库表已创建")

    task_manager = get_task_manager()
    print("✅ 任务管理器已初始化")
    print("✅ 任务队列系统已就绪")

    yield


app = FastAPI(
    title="YouTube Subtitle Service", 
    description="YouTube 字幕下载和批量处理服务",
    version="2.1.0",
    lifespan=app_lifespan
)

# 使用项目本地目录
BASE_DIR = Path(__file__).parent.absolute()
COOKIE_DIR = BASE_DIR / "cookies"
COOKIE_DIR.mkdir(exist_ok=True)

# Token 验证函数
async def verify_token(x_api_token: str = Header(None, alias="X-API-Token")):
    """
    验证API Token
    
    支持两种方式:
    1. Header: X-API-Token: Abcd123456
    2. Authorization: Bearer Abcd123456 (如果配置了TOKEN_PREFIX)
    """
    if not x_api_token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="缺少API Token，请在请求头中添加 X-API-Token",
            headers={"WWW-Authenticate": "Token"}
        )
    
    # 移除前缀（如果配置了）
    token = x_api_token
    if TOKEN_PREFIX and token.startswith(TOKEN_PREFIX + " "):
        token = token[len(TOKEN_PREFIX) + 1:]
    
    if token != API_TOKEN:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="无效的API Token",
            headers={"WWW-Authenticate": "Token"}
        )
    
    return True

# 可选：支持Authorization header的Bearer token
security = HTTPBearer(auto_error=False)

async def verify_bearer_token(credentials: HTTPAuthorizationCredentials = Depends(security)):
    """备用的Bearer token验证"""
    if not credentials:
        return None
        
    if credentials.credentials != API_TOKEN:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="无效的Bearer Token",
            headers={"WWW-Authenticate": "Bearer"}
        )
    
    return True

async def verify_any_token(
    x_api_token: str = Header(None, alias="X-API-Token"),
    bearer_token: HTTPAuthorizationCredentials = Depends(security)
):
    """
    灵活的token验证：支持X-API-Token header或Authorization Bearer
    """
    # 优先检查X-API-Token header
    if x_api_token:
        if x_api_token == API_TOKEN:
            return True
        else:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="无效的API Token"
            )
    
    # 检查Bearer token
    if bearer_token:
        if bearer_token.credentials == API_TOKEN:
            return True
        else:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="无效的Bearer Token"
            )
    
    # 都没有提供token
    raise HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="缺少认证信息，请提供 X-API-Token header 或 Authorization Bearer token",
        headers={"WWW-Authenticate": "Token, Bearer"}
    )


class SaveCookieRequest(BaseModel):
    """保存 Cookie 请求模型"""
    cookie_name: str
    cookie_content: str  # Cookie 字符串，将自动转换为 Netscape 格式


class DownloadRequest(BaseModel):
    """字幕下载请求模型"""
    url: HttpUrl
    cookie: Optional[str] = None  # Cookie 内容字符串（可选，不传则使用本地 ./cookies/ 目录的文件，自动转换为 Netscape 格式）
    subtitle_lang: str = "en"


class ChannelBatchRequest(BaseModel):
    """频道批量处理请求模型"""
    channel_url: HttpUrl
    max_videos: int = 50
    subtitle_lang: str = "en"
    cookie: Optional[str] = None  # Cookie 内容字符串（可选，自动转换为 Netscape 格式）


@app.get("/", response_class=HTMLResponse)
async def read_root():
    """返回首页HTML"""
    with open("index.html", "r", encoding="utf-8") as f:
        return f.read()

@app.get("/health")
async def health_check():
    """
    健康检查端点（无需认证）
    """
    return {
        "status": "healthy",
        "service": "YouTube Subtitle Service",
        "version": "2.1.0",
        "authentication": "enabled",
        "message": "服务正常运行，所有API需要token认证"
    }


@app.get("/auth/info")
async def auth_info(token_valid: bool = Depends(verify_any_token)):
    """
    获取认证信息（需要有效token）
    """
    return {
        "authenticated": True,
        "token_valid": True,
        "message": "Token认证成功",
        "token_methods": [
            "X-API-Token header",
            "Authorization Bearer token"
        ],
        "example_usage": {
            "curl_header": "curl -H 'X-API-Token: Abcd123456' http://localhost:8001/health",
            "curl_bearer": "curl -H 'Authorization: Bearer Abcd123456' http://localhost:8001/health"
        }
    }


@app.post("/cookie/save")
async def save_cookie(request: SaveCookieRequest, token_valid: bool = Depends(verify_any_token)):
    """
    保存 Cookie 到本地（自动转换为 Netscape 格式）
    
    请求体:
    {
        "cookie_name": "youtube_cookies",
        "cookie_content": "Cookie 内容字符串（支持 JSON、Header 等格式，自动转换为 Netscape 格式）"
    }
    """
    filename = request.cookie_name if request.cookie_name.endswith('.txt') else f"{request.cookie_name}.txt"
    cookie_path = COOKIE_DIR / filename
    
    try:
        # 转换 Cookie 字符串为 Netscape 格式
        netscape_content = cookie_string_to_netscape(request.cookie_content)
        
        with open(cookie_path, 'w', encoding='utf-8') as f:
            f.write(netscape_content)
        
        return {
            "status": "success",
            "message": f"Cookie 文件 '{filename}' 保存成功（已转换为 Netscape 格式）",
            "cookie_name": filename,
            "path": str(cookie_path),
            "format": "Netscape"
        }
    
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"保存 Cookie 失败: {str(e)}")


@app.post("/subtitle/download")
async def download_subtitles(request: DownloadRequest, token_valid: bool = Depends(verify_any_token)):
    """
    下载字幕并返回 JSON
    
    请求体:
    {
        "url": "视频 URL",
        "cookie": "cookie字符串内容",  // 可选，不传则使用本地 ./cookies/ 目录的文件，支持多种格式自动转换为 Netscape 格式
        "subtitle_lang": "en"
    }
    """
    # 处理 Cookie
    cookie_path = None
    cookie_source = None
    temp_cookie_file = None
    
    if request.cookie:
        # 如果传了cookie字符串，转换为Netscape格式并创建临时cookie文件
        temp_cookie_file = save_cookie_string_as_netscape(request.cookie)
        cookie_path = temp_cookie_file
        cookie_source = "请求参数（已转换为Netscape格式）"
        print(f"使用请求中的Cookie字符串（已转换为Netscape格式）")
    else:
        # 使用固定的cookie文件
        cookie_path = COOKIE_DIR / "cookies.txt"
        if cookie_path.exists():
            cookie_source = "本地文件: cookies.txt"
            print(f"使用Cookie文件: cookies.txt")
        else:
            cookie_path = None
            cookie_source = "无"
            print("警告: 未找到 cookies.txt，可能会遇到访问限制")
    
    # 创建临时目录用于下载字幕
    temp_dir = Path(tempfile.mkdtemp(prefix="ytbscript_temp_"))
    
    # 配置 yt-dlp 选项
    ydl_opts = {
        'skip_download': True,
        'writesubtitles': True,
        'writeautomaticsub': True,
        'subtitleslangs': [request.subtitle_lang],
        'subtitlesformat': 'vtt',
        'outtmpl': str(temp_dir / '%(title)s.%(ext)s'),
        'quiet': False,
        'no_warnings': False,
    }
    
    # 如果有cookie，添加到配置中
    if cookie_path:
        ydl_opts['cookiefile'] = str(cookie_path)
    
    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(str(request.url), download=True)
            
            # 获取下载的字幕文件
            subtitle_files = list(temp_dir.glob('*.vtt'))
            
            if not subtitle_files:
                raise HTTPException(status_code=404, detail="未找到字幕文件，该视频可能没有字幕")
            
            # 转换字幕为 JSON
            subtitles_data = []
            for subtitle_file in subtitle_files:
                try:
                    subtitle_json = vtt_to_json(str(subtitle_file))
                    subtitles_data.append({
                        "language": subtitle_file.stem.split('.')[-1],
                        "subtitle_count": len(subtitle_json),
                        "subtitles": subtitle_json
                    })
                except Exception as e:
                    raise HTTPException(status_code=500, detail=f"字幕转换失败: {str(e)}")
            
            return {
                "status": "success",
                "title": info.get('title', 'Unknown'),
                "duration": info.get('duration'),
                "uploader": info.get('uploader'),
                "subtitle_count": len(subtitles_data[0]['subtitles']) if subtitles_data else 0,
                "subtitles": subtitles_data,
                "cookie_source": cookie_source,
                "message": f"字幕下载成功，Cookie来源: {cookie_source}"
            }
    
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"下载失败: {str(e)}")
    finally:
        # 清理临时目录
        if temp_dir.exists():
            shutil.rmtree(temp_dir)
        # 清理临时cookie文件
        if temp_cookie_file and temp_cookie_file.exists():
            temp_cookie_file.unlink()


@app.post("/channel/batch-process")
async def batch_process_channel(request: ChannelBatchRequest, token_valid: bool = Depends(verify_any_token)):
    """
    创建批量处理任务（异步）
    
    请求体:
    {
        "channel_url": "https://www.youtube.com/@example",
        "max_videos": 50,
        "subtitle_lang": "en"
    }
    
    返回:
    {
        "task_id": "uuid-string",
        "status": "pending",
        "message": "任务已创建，正在队列中等待处理"
    }
    """
    try:
        from task_manager import get_task_manager, TaskType
        
        task_manager = get_task_manager()
        
        # 创建任务
        task_params = {
            'channel_url': str(request.channel_url),
            'max_videos': request.max_videos,
            'subtitle_lang': request.subtitle_lang
        }
        
        task_id = task_manager.create_task(TaskType.BATCH_PROCESS, task_params)
        
        # 立即启动任务
        await task_manager.start_task(task_id)
        
        return {
            "task_id": task_id,
            "status": "running", 
            "message": "任务已创建并开始处理",
            "check_status_url": f"/tasks/{task_id}/status"
        }
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"创建任务失败: {str(e)}")


@app.post("/channel/batch-process-sync")
async def batch_process_channel_sync(request: ChannelBatchRequest, token_valid: bool = Depends(verify_any_token)):
    """
    批量处理YouTube频道视频并提取字幕（同步版本，兼容旧接口）
    """
    try:
        from youtube_channel_processor import get_processor
        
        processor = get_processor()
        
        # 执行批量处理
        result = await processor.process_channel_batch(
            channel_url=str(request.channel_url),
            max_videos=request.max_videos,
            subtitle_lang=request.subtitle_lang,
            cookie_string=request.cookie
        )
        
        return result
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"批量处理失败: {str(e)}")


@app.get("/tasks/{task_id}/status")
async def get_task_status(task_id: str, token_valid: bool = Depends(verify_any_token)):
    """
    获取任务状态
    
    返回:
    {
        "task_id": "uuid-string",
        "status": "running",
        "progress": 45,
        "total_items": 100,
        "current_item": "正在处理: 视频标题...",
        "created_at": "2024-01-01T12:00:00",
        "result": {...}  // 仅在完成时返回
    }
    """
    try:
        from task_manager import get_task_manager
        
        task_manager = get_task_manager()
        task_info = task_manager.get_task_status(task_id)
        
        if not task_info:
            raise HTTPException(status_code=404, detail="任务不存在")
        
        return task_info
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"获取任务状态失败: {str(e)}")


@app.get("/tasks")
async def get_all_tasks(status: Optional[str] = None, limit: int = 50, token_valid: bool = Depends(verify_any_token)):
    """
    获取所有任务列表
    
    参数:
        status: 可选，筛选特定状态的任务 (pending/running/completed/failed/cancelled)
        limit: 返回数量限制
    """
    try:
        from task_manager import get_task_manager, TaskStatus
        
        task_manager = get_task_manager()
        
        # 转换状态参数
        status_filter = None
        if status:
            try:
                status_filter = TaskStatus(status)
            except ValueError:
                raise HTTPException(status_code=400, detail=f"无效的状态值: {status}")
        
        tasks = task_manager.get_all_tasks(status_filter, limit)
        
        return {
            "total_tasks": len(tasks),
            "tasks": tasks
        }
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"获取任务列表失败: {str(e)}")


@app.delete("/tasks/{task_id}")
async def cancel_task(task_id: str, token_valid: bool = Depends(verify_any_token)):
    """
    取消任务
    
    返回:
    {
        "task_id": "uuid-string",
        "status": "cancelled",
        "message": "任务已取消"
    }
    """
    try:
        from task_manager import get_task_manager
        
        task_manager = get_task_manager()
        success = task_manager.cancel_task(task_id)
        
        if not success:
            raise HTTPException(status_code=400, detail="无法取消任务，任务可能已完成或不存在")
        
        return {
            "task_id": task_id,
            "status": "cancelled",
            "message": "任务已取消"
        }
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"取消任务失败: {str(e)}")


@app.get("/channel/stats")
async def get_channel_stats(channel_id: Optional[str] = None, token_valid: bool = Depends(verify_any_token)):
    """
    获取频道统计信息
    
    参数:
        channel_id: 可选，指定频道ID获取单个频道统计，否则返回总体统计
    
    返回:
        频道统计信息
    """
    try:
        from youtube_channel_processor import get_processor
        processor = get_processor()
        stats = processor.get_channel_stats(channel_id)
        return stats
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"获取统计信息失败: {str(e)}")


@app.get("/videos/search")
async def search_videos_by_subtitle(
    query: str,
    channel_id: Optional[str] = None,
    limit: int = 20,
    token_valid: bool = Depends(verify_any_token)
):
    """
    根据字幕内容搜索视频
    
    参数:
        query: 搜索关键词
        channel_id: 可选，限制在指定频道内搜索
        limit: 返回结果数量限制
    
    返回:
        匹配的视频和字幕片段列表
    """
    try:
        from youtube_channel_processor import get_processor
        processor = get_processor()
        
        # 构建SQL查询 - 搜索JSON字段中的字幕
        with processor.get_db_connection() as conn:
            cursor = conn.cursor()
            
            if channel_id:
                cursor.execute('''
                    SELECT v.video_id, v.title, v.url, v.uploader, v.subtitle_json, v.subtitle_language
                    FROM videos v
                    WHERE v.channel_id = ? 
                    AND v.subtitle_extracted = TRUE 
                    AND v.subtitle_json LIKE ?
                    ORDER BY v.upload_date DESC
                    LIMIT ?
                ''', (channel_id, f'%{query}%', limit))
            else:
                cursor.execute('''
                    SELECT v.video_id, v.title, v.url, v.uploader, v.subtitle_json, v.subtitle_language
                    FROM videos v
                    WHERE v.subtitle_extracted = TRUE 
                    AND v.subtitle_json LIKE ?
                    ORDER BY v.upload_date DESC
                    LIMIT ?
                ''', (f'%{query}%', limit))
            
            results = cursor.fetchall()
            
            # 解析JSON并查找匹配的字幕片段
            import json
            videos = []
            
            for row in results:
                video_id, title, url, uploader, subtitle_json_str, language = row
                
                if not subtitle_json_str:
                    continue
                
                try:
                    subtitle_json = json.loads(subtitle_json_str)
                    
                    # 查找包含查询关键词的字幕片段
                    matched_segments = []
                    for segment in subtitle_json:
                        if query.lower() in segment.get('subtitle', '').lower():
                            matched_segments.append({
                                'subtitle_text': segment['subtitle'],
                                'start_time': segment['start'],
                                'end_time': segment['end'],
                                'time_range': segment['time']
                            })
                    
                    if matched_segments:
                        videos.append({
                            'video_id': video_id,
                            'title': title,
                            'url': url,
                            'uploader': uploader,
                            'subtitle_language': language,
                            'matched_segments': matched_segments,
                            'total_matches': len(matched_segments)
                        })
                        
                except json.JSONDecodeError:
                    continue
            
            return {
                'query': query,
                'total_results': len(videos),
                'videos': videos
            }
            
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"搜索失败: {str(e)}")


@app.get("/videos/{video_id}/subtitles")
async def get_video_subtitles(video_id: str, token_valid: bool = Depends(verify_any_token)):
    """
    获取指定视频的完整字幕JSON
    
    参数:
        video_id: 视频ID
    
    返回:
        视频的完整字幕数据
    """
    try:
        from youtube_channel_processor import get_processor
        processor = get_processor()
        
        with processor.get_db_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('''
                SELECT title, url, uploader, subtitle_language, subtitle_json, upload_date
                FROM videos 
                WHERE video_id = ? AND subtitle_extracted = TRUE
            ''', (video_id,))
            
            result = cursor.fetchone()
            
            if not result:
                raise HTTPException(status_code=404, detail="视频未找到或字幕未提取")
            
            title, url, uploader, language, subtitle_json_str, upload_date = result
            
            import json
            try:
                subtitle_json = json.loads(subtitle_json_str) if subtitle_json_str else []
            except json.JSONDecodeError:
                subtitle_json = []
            
            return {
                'video_id': video_id,
                'title': title,
                'url': url,
                'uploader': uploader,
                'upload_date': upload_date,
                'subtitle_language': language,
                'subtitle_count': len(subtitle_json),
                'subtitles': subtitle_json
            }
            
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"获取字幕失败: {str(e)}")


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=24314)
