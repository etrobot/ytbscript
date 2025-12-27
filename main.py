from fastapi import FastAPI, HTTPException, Depends, Header, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from fastapi.responses import HTMLResponse
from pydantic import BaseModel, HttpUrl
from typing import Optional
import yt_dlp
import shutil
from pathlib import Path
import tempfile
from subtitle_utils import vtt_to_json
from cookie_utils import save_cookie_string_as_netscape, cookie_string_to_netscape
import os
from dotenv import load_dotenv
import logging
from datetime import datetime

# 配置日志
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# 加载环境变量
load_dotenv()

# Token 配置
API_TOKEN = os.getenv("API_TOKEN", "Abcd123456")
TOKEN_HEADER = os.getenv("API_TOKEN_HEADER", "X-API-Token")
TOKEN_PREFIX = os.getenv("TOKEN_PREFIX", "")


# 导入启动模块
from startup import create_app_lifespan, get_app_config
from task_manager import get_task_manager, TaskType, TaskStatus
from youtube_channel_processor import YouTubeChannelProcessor
from scheduler_service import get_scheduler
from cookie_utils import cookie_string_to_netscape
from cookie_keepalive_service import get_keepalive_service

# 获取应用配置
app_config = get_app_config()

app = FastAPI(
    title=app_config["title"],
    description=app_config["description"], 
    version=app_config["version"],
    lifespan=create_app_lifespan()
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


@app.get("/api/services/status")
async def get_services_status():
    """
    获取所有服务运行状态
    """
    try:
        from task_manager import get_task_manager
        
        services_status = {
            "timestamp": datetime.now().isoformat(),
            "services": {
                "web_api": {
                    "status": "running",
                    "description": "FastAPI Web服务",
                    "port": 24314,
                    "version": "2.1.0"
                },
                "youtube_processor": {
                    "status": "running",
                    "description": "YouTube频道处理器"
                },
                "task_manager": {
                    "status": "running", 
                    "description": "任务队列管理器"
                }
            }
        }
        
        # 检查调度服务状态
        if hasattr(app.state, 'scheduler') and app.state.scheduler:
            scheduler_running = app.state.scheduler.scheduler.running if app.state.scheduler.scheduler else False
            thread_alive = app.state.scheduler_thread.is_alive() if app.state.scheduler_thread else False
            
            services_status["services"]["scheduler"] = {
                "status": "running" if scheduler_running and thread_alive else "stopped",
                "description": "AI总结定时调度服务",
                "scheduler_running": scheduler_running,
                "thread_alive": thread_alive,
                "job_count": len(app.state.scheduler.scheduler.get_jobs()) if scheduler_running else 0
            }
            
            # 获取D1数据库状态
            try:
                d1_status = "connected"
                # 简单测试D1连接
                app.state.scheduler.d1.execute("SELECT 1")
            except Exception as e:
                d1_status = f"error: {str(e)}"
                
            services_status["services"]["d1_database"] = {
                "status": "connected" if d1_status == "connected" else "error",
                "description": "Cloudflare D1数据库",
                "details": d1_status
            }
            
            # 获取OpenAI API状态
            openai_configured = bool(os.getenv("OPENAI_API_KEY"))
            services_status["services"]["openai_api"] = {
                "status": "configured" if openai_configured else "not_configured",
                "description": "OpenAI API服务",
                "model": os.getenv("OPENAI_MODEL", "未配置"),
                "base_url": os.getenv("OPENAI_BASE_URL", "default")
            }
        else:
            services_status["services"]["scheduler"] = {
                "status": "not_started",
                "description": "AI总结定时调度服务",
                "error": "调度服务未启动或启动失败"
            }
            
        # 获取任务管理器统计
        try:
            task_manager = get_task_manager()
            # 检查是否有运行中的任务
            has_tasks = task_manager.has_running_tasks()
            services_status["services"]["task_manager"]["has_running_tasks"] = has_tasks
        except Exception as e:
            services_status["services"]["task_manager"]["error"] = str(e)
        
        # 获取Cookie保活服务状态
        try:
            keepalive = get_keepalive_service(COOKIE_DIR)
            keepalive_status = keepalive.get_status()
            services_status["services"]["cookie_keepalive"] = {
                "status": "running" if keepalive_status['running'] else "stopped",
                "description": "Cookie保活服务",
                "paused": keepalive_status['paused'],
                "check_interval": keepalive_status['check_interval'],
                "active_cookie": keepalive_status['active_cookie'],
                "cookies": keepalive_status['cookies']
            }
        except Exception as e:
            services_status["services"]["cookie_keepalive"] = {
                "status": "not_initialized",
                "description": "Cookie保活服务",
                "error": str(e)
            }
            
        # 检查本地数据库
        try:
            from youtube_channel_processor import get_processor
            processor = get_processor()
            with processor.get_db_connection() as conn:
                cursor = conn.cursor()
                cursor.execute("SELECT COUNT(*) FROM videos")
                video_count = cursor.fetchone()[0]
                cursor.execute("SELECT COUNT(*) FROM channels") 
                channel_count = cursor.fetchone()[0]
                cursor.execute("SELECT COUNT(*) FROM videos WHERE subtitle_extracted = 1")
                subtitle_count = cursor.fetchone()[0]
                
            services_status["services"]["local_database"] = {
                "status": "connected",
                "description": "本地SQLite数据库", 
                "statistics": {
                    "total_videos": video_count,
                    "total_channels": channel_count,
                    "videos_with_subtitles": subtitle_count
                }
            }
        except Exception as e:
            services_status["services"]["local_database"] = {
                "status": "error",
                "description": "本地SQLite数据库",
                "error": str(e)
            }
        
        return services_status
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"获取服务状态失败: {str(e)}")


@app.get("/api/scheduler/tasks")
async def get_scheduled_tasks():
    """
    获取所有定时任务
    """
    result = {
        "scheduler_status": "unknown",
        "scheduled_tasks": [],
        "recent_headlines": [],
        "scheduler_jobs": [],
        "errors": []
    }
    
    try:
        if not hasattr(app.state, 'scheduler') or not app.state.scheduler:
            result["scheduler_status"] = "not_started"
            result["errors"].append("调度服务未启动")
            return result
            
        scheduler = app.state.scheduler
        result["scheduler_status"] = "running" if scheduler.scheduler.running else "stopped"
        
        # 获取APScheduler中的任务
        try:
            result["scheduler_jobs"] = [
                {
                    "id": str(job.id),
                    "name": job.name,
                    "next_run": job.next_run_time.isoformat() if job.next_run_time else None,
                    "trigger": str(job.trigger),
                    "func": str(job.func)
                }
                for job in scheduler.scheduler.get_jobs()
            ]
        except Exception as e:
            result["errors"].append(f"获取调度任务失败: {str(e)}")
        
        # 尝试从D1数据库获取定时任务
        try:
            tasks = scheduler.d1.fetch_all("SELECT * FROM scheduled_tasks ORDER BY createdAt DESC")
            result["scheduled_tasks"] = tasks
        except Exception as e:
            result["errors"].append(f"D1数据库scheduled_tasks查询失败: {str(e)}")
        
        # 尝试从D1数据库获取AI生成的headlines
        try:
            headlines = scheduler.d1.fetch_all("SELECT * FROM ai_headlines ORDER BY createdAt DESC LIMIT 10")
            result["recent_headlines"] = headlines
        except Exception as e:
            result["errors"].append(f"D1数据库ai_headlines查询失败: {str(e)}")
        
        return result
        
    except Exception as e:
        result["errors"].append(f"调度器状态检查失败: {str(e)}")
        return result


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


@app.post("/api/save_cookie")
async def save_cookie(request: SaveCookieRequest, token_valid: bool = Depends(verify_any_token)):
    """
    保存/更新 Cookie（保存后自动启动保活服务）
    
    请求体:
    {
        "cookie_name": "youtube_cookies",
        "cookie_content": "Cookie内容（自动转换为Netscape格式）"
    }
    """
    filename = request.cookie_name if request.cookie_name.endswith('.txt') else f"{request.cookie_name}.txt"
    cookie_path = COOKIE_DIR / filename
    
    try:
        netscape_content = cookie_string_to_netscape(request.cookie_content)
        
        with open(cookie_path, 'w', encoding='utf-8') as f:
            f.write(netscape_content)
        
        # 注册cookie到保活服务
        try:
            keepalive = get_keepalive_service(COOKIE_DIR)
            keepalive.register_cookie(filename, cookie_path)
            
            # 如果保活服务未运行，启动它
            if not keepalive.running:
                keepalive.start()
                logger.info("Cookie保活服务已启动")
            
            return {
                "status": "success",
                "message": f"Cookie已保存并启动保活: {filename}",
                "path": str(cookie_path),
                "keepalive_enabled": True
            }
        except Exception as e:
            logger.warning(f"启动保活服务失败: {e}")
            return {
                "status": "success",
                "message": f"Cookie已保存: {filename}（保活服务启动失败）",
                "path": str(cookie_path),
                "keepalive_enabled": False,
                "keepalive_error": str(e)
            }
    
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"保存Cookie失败: {str(e)}")


@app.post("/api/subtitle")
async def get_subtitle(request: DownloadRequest, token_valid: bool = Depends(verify_any_token)):
    """
    获取字幕（智能：优先从数据库读取，不存在则下载并保存）
    
    请求体:
    {
        "url": "视频 URL",
        "subtitle_lang": "en",
        "cookie": "可选"
    }
    """
    try:
        from youtube_channel_processor import get_processor
        import json
        
        # 从URL提取video_id
        video_url = str(request.url)
        video_id = None
        
        if "watch?v=" in video_url:
            video_id = video_url.split("watch?v=")[-1].split("&")[0]
        elif "youtu.be/" in video_url:
            video_id = video_url.split("youtu.be/")[-1].split("?")[0]
        elif "/shorts/" in video_url:
            video_id = video_url.split("/shorts/")[-1].split("?")[0]
        
        if not video_id or len(video_id) != 11:
            raise HTTPException(status_code=400, detail="无效的YouTube视频URL")
        
        processor = get_processor()
        
        # 1. 先查数据库
        with processor.get_db_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('''
                SELECT title, url, uploader, subtitle_language, subtitle_json, upload_date
                FROM videos 
                WHERE video_id = ? AND subtitle_extracted = TRUE
            ''', (video_id,))
            
            result = cursor.fetchone()
            
            if result:
                title, url, uploader, language, subtitle_json_str, upload_date = result
                subtitle_json = json.loads(subtitle_json_str) if subtitle_json_str else []
                
                return {
                    'status': 'success',
                    'source': 'database',
                    'video_id': video_id,
                    'title': title,
                    'url': url,
                    'uploader': uploader,
                    'upload_date': upload_date,
                    'subtitle_language': language,
                    'subtitle_count': len(subtitle_json),
                    'subtitles': subtitle_json
                }
        
        # 2. 数据库没有，下载
        logger.info(f"数据库未找到视频 {video_id}，开始下载...")
        
        cookie_path = None
        temp_cookie_file = None
        
        if request.cookie:
            temp_cookie_file = save_cookie_string_as_netscape(request.cookie)
            cookie_path = temp_cookie_file
        else:
            cookie_path = COOKIE_DIR / "cookies.txt"
            if not cookie_path.exists():
                cookie_path = None
        
        temp_dir = Path(tempfile.mkdtemp(prefix="ytbscript_temp_"))
        
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
        
        if cookie_path:
            ydl_opts['cookiefile'] = str(cookie_path)
        
        try:
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                info = ydl.extract_info(video_url, download=True)
                
                subtitle_files = list(temp_dir.glob('*.vtt'))
                
                if not subtitle_files:
                    raise HTTPException(status_code=404, detail="未找到字幕文件")
                
                subtitle_json = vtt_to_json(str(subtitle_files[0]))
                
                # 3. 保存到数据库
                title = info.get('title', 'Unknown')
                uploader = info.get('uploader', 'Unknown')
                duration = info.get('duration')
                upload_date = info.get('upload_date')
                channel_id = info.get('channel_id') or info.get('uploader_id') or 'unknown'
                
                with processor.get_db_connection() as conn:
                    cursor = conn.cursor()
                    
                    cursor.execute('''
                        INSERT OR IGNORE INTO videos 
                        (video_id, channel_id, title, url, duration, upload_date, uploader, subtitle_extracted, subtitle_language, subtitle_json)
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    ''', (video_id, channel_id, title, video_url, duration, upload_date, uploader, False, None, None))
                    
                    cursor.execute('''
                        UPDATE videos SET 
                            subtitle_extracted = TRUE,
                            subtitle_language = ?,
                            subtitle_json = ?
                        WHERE video_id = ?
                    ''', (request.subtitle_lang, json.dumps(subtitle_json, ensure_ascii=False), video_id))
                    
                    conn.commit()
                
                logger.info(f"视频 {video_id} 字幕已保存到数据库")
                
                return {
                    'status': 'success',
                    'source': 'downloaded',
                    'video_id': video_id,
                    'title': title,
                    'duration': duration,
                    'uploader': uploader,
                    'upload_date': upload_date,
                    'subtitle_language': request.subtitle_lang,
                    'subtitle_count': len(subtitle_json),
                    'subtitles': subtitle_json
                }
        
        finally:
            if temp_dir.exists():
                shutil.rmtree(temp_dir)
            if temp_cookie_file and temp_cookie_file.exists():
                temp_cookie_file.unlink()
    
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"获取字幕失败: {str(e)}")


@app.post("/api/channel_task")
async def channel_task(request: ChannelBatchRequest, token_valid: bool = Depends(verify_any_token)):
    """
    启动频道更新任务（异步）
    
    请求体:
    {
        "channel_url": "https://www.youtube.com/@channel",
        "max_videos": 50,
        "subtitle_lang": "en"
    }
    
    返回任务ID，可通过 /api/channel_task/{task_id} 查询状态
    """
    try:
        from task_manager import get_task_manager, TaskType
        
        task_manager = get_task_manager()
        
        task_params = {
            'channel_url': str(request.channel_url),
            'max_videos': request.max_videos,
            'subtitle_lang': request.subtitle_lang
        }
        
        task_id = task_manager.create_task(TaskType.BATCH_PROCESS, task_params)
        await task_manager.start_task(task_id)
        
        return {
            "task_id": task_id,
            "status": "running",
            "message": "频道更新任务已启动"
        }
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"启动任务失败: {str(e)}")


@app.get("/api/channel_task/{task_id}")
async def get_task_status(task_id: str, token_valid: bool = Depends(verify_any_token)):
    """
    查询频道任务状态
    
    返回任务进度和结果
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


@app.get("/api/cookie/keepalive/status")
async def get_keepalive_status(token_valid: bool = Depends(verify_any_token)):
    """
    获取Cookie保活服务状态
    
    返回保活服务的详细状态信息
    """
    try:
        from cookie_keepalive_service import get_keepalive_service
        keepalive = get_keepalive_service(COOKIE_DIR)
        status = keepalive.get_status()
        
        return {
            "status": "success",
            "keepalive_service": status
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"获取保活状态失败: {str(e)}")


@app.post("/api/cookie/keepalive/control")
async def control_keepalive(action: str, token_valid: bool = Depends(verify_any_token)):
    """
    控制Cookie保活服务
    
    参数:
        action: 'start', 'pause', 'resume', 'stop'
    """
    try:
        from cookie_keepalive_service import get_keepalive_service
        keepalive = get_keepalive_service(COOKIE_DIR)
        
        if action == 'start':
            if keepalive.running:
                return {"status": "info", "message": "保活服务已在运行"}
            keepalive.start()
            return {"status": "success", "message": "保活服务已启动"}
        
        elif action == 'pause':
            keepalive.pause()
            return {"status": "success", "message": "保活服务已暂停"}
        
        elif action == 'resume':
            keepalive.resume()
            return {"status": "success", "message": "保活服务已恢复"}
        
        elif action == 'stop':
            await keepalive.stop()
            return {"status": "success", "message": "保活服务已停止"}
        
        else:
            raise HTTPException(status_code=400, detail=f"无效的操作: {action}")
    
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"控制保活服务失败: {str(e)}")

if __name__ == "__main__":
    # 使用startup.py启动
    from startup import start_server
    start_server()
