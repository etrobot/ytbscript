from fastapi import FastAPI, HTTPException, UploadFile, File
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel, HttpUrl
from typing import Optional
import yt_dlp
import os
import tempfile
import shutil
from pathlib import Path
import json

app = FastAPI(
    title="YouTube Downloader Service",
    description="基于 FastAPI 和 yt-dlp 的视频下载服务，支持 cookie 和字幕下载",
    version="1.0.0"
)

# 创建临时下载目录
DOWNLOAD_DIR = Path(tempfile.gettempdir()) / "ytbscript_downloads"
DOWNLOAD_DIR.mkdir(exist_ok=True)

# 创建 cookie 存储目录
COOKIE_DIR = Path(tempfile.gettempdir()) / "ytbscript_cookies"
COOKIE_DIR.mkdir(exist_ok=True)


class DownloadRequest(BaseModel):
    """下载请求模型"""
    url: HttpUrl
    use_cookie: bool = False
    cookie_name: Optional[str] = None
    download_subtitles: bool = True
    subtitle_lang: str = "en"  # 默认英文字幕
    format_quality: str = "best"  # best, worst, 或具体格式如 "bestvideo+bestaudio"


class VideoInfo(BaseModel):
    """视频信息模型"""
    title: str
    duration: Optional[int]
    uploader: Optional[str]
    description: Optional[str]
    thumbnail: Optional[str]
    formats: list


@app.get("/")
async def root():
    """根路径，返回 API 信息"""
    return {
        "message": "YouTube Downloader Service",
        "version": "1.0.0",
        "endpoints": {
            "info": "/info?url=<video_url>",
            "download": "/download (POST)",
            "upload_cookie": "/cookie/upload (POST)",
            "list_cookies": "/cookie/list (GET)",
            "delete_cookie": "/cookie/{cookie_name} (DELETE)"
        }
    }


@app.get("/info")
async def get_video_info(url: str, use_cookie: bool = False, cookie_name: Optional[str] = None):
    """
    获取视频信息
    
    参数:
    - url: 视频 URL
    - use_cookie: 是否使用 cookie
    - cookie_name: cookie 文件名（如果 use_cookie=True）
    """
    ydl_opts = {
        'quiet': True,
        'no_warnings': True,
    }
    
    # 如果需要使用 cookie
    if use_cookie and cookie_name:
        cookie_path = COOKIE_DIR / cookie_name
        if not cookie_path.exists():
            raise HTTPException(status_code=404, detail=f"Cookie 文件 '{cookie_name}' 不存在")
        ydl_opts['cookiefile'] = str(cookie_path)
    
    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=False)
            
            return VideoInfo(
                title=info.get('title', 'Unknown'),
                duration=info.get('duration'),
                uploader=info.get('uploader'),
                description=info.get('description'),
                thumbnail=info.get('thumbnail'),
                formats=[{
                    'format_id': f.get('format_id'),
                    'ext': f.get('ext'),
                    'resolution': f.get('resolution'),
                    'filesize': f.get('filesize')
                } for f in info.get('formats', [])]
            )
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"获取视频信息失败: {str(e)}")


@app.post("/download")
async def download_video(request: DownloadRequest):
    """
    下载视频和字幕
    
    请求体:
    {
        "url": "视频 URL",
        "use_cookie": false,
        "cookie_name": "cookies.txt",
        "download_subtitles": true,
        "subtitle_lang": "en",
        "format_quality": "best"
    }
    """
    # 创建唯一的下载目录
    download_path = DOWNLOAD_DIR / f"download_{os.urandom(8).hex()}"
    download_path.mkdir(exist_ok=True)
    
    # 配置 yt-dlp 选项
    ydl_opts = {
        'format': request.format_quality,
        'outtmpl': str(download_path / '%(title)s.%(ext)s'),
        'quiet': False,
        'no_warnings': False,
    }
    
    # 如果需要下载字幕
    if request.download_subtitles:
        ydl_opts.update({
            'writesubtitles': True,
            'writeautomaticsub': True,  # 也尝试自动生成的字幕
            'subtitleslangs': [request.subtitle_lang],
            'subtitlesformat': 'vtt',  # 指定 VTT 格式
            'skip_download': False,  # 同时下载视频
        })
    
    # 如果需要使用 cookie
    if request.use_cookie and request.cookie_name:
        cookie_path = COOKIE_DIR / request.cookie_name
        if not cookie_path.exists():
            raise HTTPException(status_code=404, detail=f"Cookie 文件 '{request.cookie_name}' 不存在")
        ydl_opts['cookiefile'] = str(cookie_path)
    
    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(str(request.url), download=True)
            
            # 获取下载的文件
            downloaded_files = list(download_path.glob('*'))
            
            video_file = None
            subtitle_files = []
            
            for file in downloaded_files:
                if file.suffix in ['.mp4', '.webm', '.mkv', '.flv']:
                    video_file = file
                elif file.suffix == '.vtt':
                    subtitle_files.append(file)
            
            return {
                "status": "success",
                "title": info.get('title', 'Unknown'),
                "video_file": str(video_file) if video_file else None,
                "subtitle_files": [str(f) for f in subtitle_files],
                "download_path": str(download_path),
                "message": f"下载完成！视频: {video_file.name if video_file else 'N/A'}, 字幕: {len(subtitle_files)} 个"
            }
    
    except Exception as e:
        # 清理下载目录
        if download_path.exists():
            shutil.rmtree(download_path)
        raise HTTPException(status_code=500, detail=f"下载失败: {str(e)}")


@app.post("/cookie/upload")
async def upload_cookie(file: UploadFile = File(...), cookie_name: Optional[str] = None):
    """
    上传 cookie 文件
    
    参数:
    - file: cookie 文件（Netscape 格式的 cookies.txt）
    - cookie_name: 自定义 cookie 文件名（可选）
    """
    # 确定 cookie 文件名
    if cookie_name:
        filename = cookie_name if cookie_name.endswith('.txt') else f"{cookie_name}.txt"
    else:
        filename = file.filename or "cookies.txt"
    
    cookie_path = COOKIE_DIR / filename
    
    try:
        # 保存上传的 cookie 文件
        with open(cookie_path, 'wb') as f:
            content = await file.read()
            f.write(content)
        
        return {
            "status": "success",
            "message": f"Cookie 文件 '{filename}' 上传成功",
            "cookie_name": filename,
            "path": str(cookie_path)
        }
    
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"上传 cookie 失败: {str(e)}")


@app.get("/cookie/list")
async def list_cookies():
    """列出所有已上传的 cookie 文件"""
    cookies = list(COOKIE_DIR.glob('*.txt'))
    
    return {
        "cookies": [
            {
                "name": cookie.name,
                "path": str(cookie),
                "size": cookie.stat().st_size
            }
            for cookie in cookies
        ],
        "count": len(cookies)
    }


@app.delete("/cookie/{cookie_name}")
async def delete_cookie(cookie_name: str):
    """删除指定的 cookie 文件"""
    cookie_path = COOKIE_DIR / cookie_name
    
    if not cookie_path.exists():
        raise HTTPException(status_code=404, detail=f"Cookie 文件 '{cookie_name}' 不存在")
    
    try:
        cookie_path.unlink()
        return {
            "status": "success",
            "message": f"Cookie 文件 '{cookie_name}' 已删除"
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"删除 cookie 失败: {str(e)}")


@app.get("/download/file/{download_id}/{filename}")
async def get_downloaded_file(download_id: str, filename: str):
    """
    获取下载的文件
    
    参数:
    - download_id: 下载 ID（从 /download 响应中获取）
    - filename: 文件名
    """
    file_path = DOWNLOAD_DIR / f"download_{download_id}" / filename
    
    if not file_path.exists():
        raise HTTPException(status_code=404, detail="文件不存在")
    
    return FileResponse(
        path=file_path,
        filename=filename,
        media_type='application/octet-stream'
    )


@app.delete("/cleanup")
async def cleanup_downloads():
    """清理所有下载的文件"""
    try:
        if DOWNLOAD_DIR.exists():
            shutil.rmtree(DOWNLOAD_DIR)
            DOWNLOAD_DIR.mkdir(exist_ok=True)
        
        return {
            "status": "success",
            "message": "所有下载文件已清理"
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"清理失败: {str(e)}")


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
