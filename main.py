from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, HttpUrl
from typing import Optional
import yt_dlp
import shutil
from pathlib import Path
import re
import tempfile

app = FastAPI(
    title="YouTube Subtitle Service",
    description="YouTube 字幕下载服务",
    version="2.0.0"
)

# 使用项目本地目录
BASE_DIR = Path(__file__).parent.absolute()
COOKIE_DIR = BASE_DIR / "cookies"
COOKIE_DIR.mkdir(exist_ok=True)


class SaveCookieRequest(BaseModel):
    """保存 Cookie 请求模型"""
    cookie_name: str
    cookie_content: str


class DownloadRequest(BaseModel):
    """字幕下载请求模型"""
    url: HttpUrl
    cookie_file: str  # Cookie 文件名（从 ./cookies/ 目录读取）
    subtitle_lang: str = "en"


def vtt_to_json(vtt_path):
    """
    将 VTT 字幕文件转换为 JSON 格式，处理重叠的时间戳并去重
    """
    try:
        with open(vtt_path, 'r', encoding='utf-8') as f:
            content = f.read()

        # 移除 WEBVTT 头部信息
        content = re.sub(r'^WEBVTT.*?\n\n', '', content, flags=re.DOTALL)

        # 分割成字幕块
        blocks = re.split(r'\n\n+', content.strip())

        # 第一步：解析并去除完全重复的字幕
        unique_subtitles = []
        time_re = re.compile(r'(\d{2}:\d{2}:\d{2}\.\d{3}) --> (\d{2}:\d{2}:\d{2}\.\d{3})')
        seen_subtitles = set()

        if len(blocks) > 0:
            for block in blocks:
                lines = block.strip().split('\n')
                if len(lines) < 2:
                    continue

                # 查找时间行
                time_match = None
                for line in lines:
                    match = time_re.search(line)
                    if match:
                        time_match = match
                        break

                if not time_match:
                    continue

                start_time, end_time = time_match.groups()

                # 获取字幕文本（跳过时间行和 align/position 信息）
                subtitle_lines = []
                for line in lines:
                    if time_re.search(line) or 'align:' in line or 'position:' in line:
                        continue
                    clean_line = re.sub(r'<[^>]+>', '', line)
                    clean_line = re.sub(r'<\d{2}:\d{2}:\d{2}\.\d{3}>', '', clean_line)
                    if clean_line.strip():
                        subtitle_lines.append(clean_line.strip())

                subtitle_text = ' '.join(subtitle_lines).strip()

                if not subtitle_text:
                    continue

                # 使用时间戳+文本作为唯一标识
                subtitle_key = f"{start_time}_{end_time}_{subtitle_text}"

                if subtitle_key in seen_subtitles:
                    continue

                seen_subtitles.add(subtitle_key)

                unique_subtitles.append({
                    "time": f"{start_time} --> {end_time}",
                    "start": start_time,
                    "end": end_time,
                    "subtitle": subtitle_text
                })

        # 第二步：处理相邻字幕的重复部分
        processed_subtitles = []
        for i, item in enumerate(unique_subtitles):
            current_text = item['subtitle']

            if i == 0:
                processed_subtitles.append(item)
                continue

            prev_text = processed_subtitles[-1]['subtitle']

            if current_text in prev_text:
                continue

            if current_text.startswith(prev_text):
                current_text = current_text[len(prev_text):].strip()

            if current_text.strip():
                new_item = item.copy()
                new_item['subtitle'] = current_text
                processed_subtitles.append(new_item)

        return processed_subtitles

    except Exception as e:
        raise HTTPException(status_code=500, detail=f"转换 VTT 到 JSON 时出错: {str(e)}")


@app.post("/cookie/save")
async def save_cookie(request: SaveCookieRequest):
    """
    保存 Cookie 到本地
    
    请求体:
    {
        "cookie_name": "youtube_cookies",
        "cookie_content": "Cookie 内容字符串"
    }
    """
    filename = request.cookie_name if request.cookie_name.endswith('.txt') else f"{request.cookie_name}.txt"
    cookie_path = COOKIE_DIR / filename
    
    try:
        with open(cookie_path, 'w', encoding='utf-8') as f:
            f.write(request.cookie_content)
        
        return {
            "status": "success",
            "message": f"Cookie 文件 '{filename}' 保存成功",
            "cookie_name": filename,
            "path": str(cookie_path)
        }
    
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"保存 Cookie 失败: {str(e)}")


@app.post("/subtitle/download")
async def download_subtitles(request: DownloadRequest):
    """
    下载字幕并返回 JSON，同时更新 Cookie
    
    请求体:
    {
        "url": "视频 URL",
        "cookie_file": "youtube_cookies.txt",
        "subtitle_lang": "en"
    }
    """
    # 检查 Cookie 文件是否存在
    cookie_path = COOKIE_DIR / request.cookie_file
    if not cookie_path.exists():
        raise HTTPException(status_code=404, detail=f"Cookie 文件 '{request.cookie_file}' 不存在")
    
    # 创建临时目录用于下载字幕
    temp_dir = Path(tempfile.mkdtemp(prefix="ytbscript_temp_"))
    
    # 配置 yt-dlp 选项
    ydl_opts = {
        'skip_download': True,
        'writesubtitles': True,
        'writeautomaticsub': True,
        'subtitleslangs': [request.subtitle_lang],
        'subtitlesformat': 'vtt',
        'cookiefile': str(cookie_path),
        'outtmpl': str(temp_dir / '%(title)s.%(ext)s'),
        'quiet': False,
        'no_warnings': False,
    }
    
    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(str(request.url), download=True)
            
            # 更新 Cookie 文件
            # yt-dlp 会自动更新 cookiefile 指定的文件
            
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
                "message": "字幕下载成功，Cookie 已更新"
            }
    
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"下载失败: {str(e)}")
    finally:
        # 清理临时目录
        if temp_dir.exists():
            shutil.rmtree(temp_dir)


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
