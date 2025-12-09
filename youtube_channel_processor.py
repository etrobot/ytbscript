"""
YouTube Channel Batch Processor
批量获取YouTube频道最新视频并提取字幕存储到SQLite数据库
"""

import sqlite3
import asyncio
import yt_dlp
import json
import tempfile
import shutil
from pathlib import Path
from typing import List, Dict, Optional, Tuple
from datetime import datetime
from subtitle_utils import vtt_to_json
from cookie_utils import save_cookie_string_as_netscape
import logging

# 配置日志
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# 数据库配置
BASE_DIR = Path(__file__).parent.absolute()
DB_PATH = BASE_DIR / "youtube_channels.db"
COOKIE_DIR = BASE_DIR / "cookies"


class YouTubeChannelProcessor:
    """YouTube频道批量处理器"""
    
    def __init__(self, db_path: str = None):
        self.db_path = db_path or str(DB_PATH)
        self.init_database()
    
    def init_database(self):
        """初始化SQLite数据库"""
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            
            # 创建频道表
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS channels (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    channel_id TEXT UNIQUE NOT NULL,
                    channel_name TEXT NOT NULL,
                    channel_url TEXT NOT NULL,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    last_processed TIMESTAMP
                )
            ''')
            
            # 创建视频表
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS videos (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    video_id TEXT UNIQUE NOT NULL,
                    channel_id TEXT NOT NULL,
                    title TEXT NOT NULL,
                    url TEXT NOT NULL,
                    duration INTEGER,
                    upload_date TEXT,
                    uploader TEXT,
                    processed_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    subtitle_extracted BOOLEAN DEFAULT FALSE,
                    subtitle_language TEXT,
                    subtitle_json TEXT,
                    FOREIGN KEY (channel_id) REFERENCES channels (channel_id)
                )
            ''')
            
            # 创建索引
            cursor.execute('CREATE INDEX IF NOT EXISTS idx_videos_channel_id ON videos (channel_id)')
            cursor.execute('CREATE INDEX IF NOT EXISTS idx_videos_upload_date ON videos (upload_date)')
            cursor.execute('CREATE INDEX IF NOT EXISTS idx_videos_subtitle_extracted ON videos (subtitle_extracted)')
            
            conn.commit()
            logger.info("数据库初始化完成")
    
    def get_channel_videos(self, channel_url: str, max_videos: int = 50, cookie_string: Optional[str] = None) -> List[Dict]:
        """
        获取频道最新视频列表
        
        Args:
            channel_url: YouTube频道URL
            max_videos: 最大视频数量
            cookie_string: 可选的cookie字符串，自动转换为Netscape格式
            
        Returns:
            视频信息列表
        """
        # 配置yt-dlp选项
        ydl_opts = {
            'quiet': True,
            'no_warnings': True,
            # 不使用 extract_flat，获取完整的视频信息
            'playlistend': max_videos,  # 限制视频数量
        }
        
        # 处理Cookie
        temp_cookie_file = None
        if cookie_string:
            # 使用传入的cookie字符串，转换为Netscape格式
            temp_cookie_file = save_cookie_string_as_netscape(cookie_string)
            ydl_opts['cookiefile'] = str(temp_cookie_file)
            logger.info("使用传入的Cookie字符串（已转换为Netscape格式）")
        else:
            # 使用固定的cookie文件
            cookie_path = COOKIE_DIR / "cookies.txt"
            if cookie_path.exists():
                ydl_opts['cookiefile'] = str(cookie_path)
                logger.info("使用Cookie文件: cookies.txt")
            else:
                logger.warning("未找到 cookies.txt，可能会遇到访问限制")
        
        def _flatten_entries(entries):
            """展开嵌套的 playlist，确保获取真实视频条目"""
            flat = []
            queue = list(entries)
            while queue:
                entry = queue.pop(0)
                if not entry:
                    continue
                entry_type = entry.get('_type')
                if entry_type == 'playlist' and entry.get('entries'):
                    queue = entry['entries'] + queue
                    continue
                flat.append(entry)
            return flat

        try:
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                info = ydl.extract_info(channel_url, download=False)
                
                if not info:
                    raise ValueError("无法获取频道信息")
                
                # 获取频道信息
                channel_info = {
                    'channel_id': info.get('id', ''),
                    'channel_name': info.get('title', ''),
                    'channel_url': channel_url
                }
                
                # 获取视频列表
                videos = []
                entries = _flatten_entries(info.get('entries', []))
                
                for entry in entries:
                    if len(videos) >= max_videos:
                        break
                    if entry:
                        entry_type = entry.get('_type')
                        if entry_type and entry_type not in (None, 'url', 'video'):
                            logger.debug(f"跳过非视频条目: type={entry_type}, title={entry.get('title', '')}")
                            continue
                        video_id = entry.get('id', '')
                        raw_url = entry.get('url') or entry.get('webpage_url')
                        if raw_url and ("watch?v=" in raw_url or "/shorts/" in raw_url):
                            video_url = raw_url
                        elif video_id and len(video_id) == 11:
                            video_url = f"https://www.youtube.com/watch?v={video_id}"
                        else:
                            logger.warning(f"跳过无法识别的视频条目: id={video_id}, url={raw_url}")
                            continue
                        
                        video_info = {
                            'video_id': video_id,
                            'title': entry.get('title', ''),
                            'url': video_url,
                            'duration': entry.get('duration'),
                            'upload_date': entry.get('upload_date'),
                            'uploader': entry.get('uploader') or channel_info['channel_name']
                        }
                        videos.append(video_info)
                
                logger.info(f"获取到 {len(videos)} 个视频")
                return channel_info, videos
                
        except Exception as e:
            logger.error(f"获取频道视频失败: {str(e)}")
            raise
        finally:
            # 清理临时cookie文件
            if temp_cookie_file and temp_cookie_file.exists():
                temp_cookie_file.unlink()
    
    def save_channel_and_videos(self, channel_info: Dict, videos: List[Dict]):
        """
        保存频道和视频信息到数据库
        
        Args:
            channel_info: 频道信息
            videos: 视频列表
        """
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            
            # 保存或更新频道信息
            cursor.execute('''
                INSERT OR REPLACE INTO channels (channel_id, channel_name, channel_url, last_processed)
                VALUES (?, ?, ?, ?)
            ''', (
                channel_info['channel_id'],
                channel_info['channel_name'],
                channel_info['channel_url'],
                datetime.now()
            ))
            
            # 保存视频信息
            for video in videos:
                cursor.execute('''
                    INSERT OR IGNORE INTO videos 
                    (video_id, channel_id, title, url, duration, upload_date, uploader, subtitle_extracted, subtitle_language, subtitle_json)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ''', (
                    video['video_id'],
                    channel_info['channel_id'],
                    video['title'],
                    video['url'],
                    video['duration'],
                    video['upload_date'],
                    video['uploader'],
                    False,  # subtitle_extracted
                    None,   # subtitle_language
                    None    # subtitle_json
                ))
            
            conn.commit()
            logger.info(f"保存了频道 '{channel_info['channel_name']}' 和 {len(videos)} 个视频")
    
    def extract_video_subtitles(self, video_id: str, video_url: str, 
                              subtitle_lang: str = "en", cookie_string: Optional[str] = None) -> Optional[List[Dict]]:
        """
        提取单个视频的字幕
        
        Args:
            video_id: 视频ID
            video_url: 视频URL
            subtitle_lang: 字幕语言
            cookie_string: 可选的cookie字符串，自动转换为Netscape格式
            
        Returns:
            字幕数据列表或None
        """
        temp_dir = Path(tempfile.mkdtemp(prefix="ytbscript_batch_"))
        
        ydl_opts = {
            'skip_download': True,
            'writesubtitles': True,
            'writeautomaticsub': True,
            'subtitleslangs': [subtitle_lang],
            'subtitlesformat': 'vtt',
            'outtmpl': str(temp_dir / '%(title)s.%(ext)s'),
            'quiet': True,
            'no_warnings': True,
        }
        
        # 处理Cookie
        temp_cookie_file = None
        if cookie_string:
            # 使用传入的cookie字符串，转换为Netscape格式
            temp_cookie_file = save_cookie_string_as_netscape(cookie_string)
            ydl_opts['cookiefile'] = str(temp_cookie_file)
        else:
            # 使用固定的cookie文件
            cookie_path = COOKIE_DIR / "cookies.txt"
            if cookie_path.exists():
                ydl_opts['cookiefile'] = str(cookie_path)
        
        try:
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                info = ydl.extract_info(video_url, download=True)
                
                # 查找字幕文件
                subtitle_files = list(temp_dir.glob('*.vtt'))
                
                if not subtitle_files:
                    logger.warning(f"视频 {video_id} 没有找到字幕文件")
                    return None
                
                # 转换字幕为JSON格式
                subtitle_file = subtitle_files[0]  # 使用第一个字幕文件
                try:
                    subtitle_json = vtt_to_json(str(subtitle_file))
                    logger.info(f"视频 {video_id} 提取到 {len(subtitle_json)} 条字幕")
                    return {
                        'language': subtitle_lang,
                        'subtitles': subtitle_json
                    }
                except Exception as e:
                    logger.error(f"转换字幕失败 {subtitle_file}: {str(e)}")
                    return None
                
        except Exception as e:
            logger.error(f"提取视频 {video_id} 字幕失败: {str(e)}")
            return None
        finally:
            # 清理临时目录
            if temp_dir.exists():
                shutil.rmtree(temp_dir)
            # 清理临时cookie文件
            if temp_cookie_file and temp_cookie_file.exists():
                temp_cookie_file.unlink()
    
    def save_subtitles(self, subtitles_data: Dict, video_id: str):
        """
        保存字幕JSON到数据库
        
        Args:
            subtitles_data: 字幕数据字典 {'language': 'en', 'subtitles': [...]}
            video_id: 视频ID
        """
        if not subtitles_data:
            return
        
        import json
        
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            
            # 更新视频的字幕信息
            cursor.execute('''
                UPDATE videos SET 
                    subtitle_extracted = TRUE,
                    subtitle_language = ?,
                    subtitle_json = ?
                WHERE video_id = ?
            ''', (
                subtitles_data['language'],
                json.dumps(subtitles_data['subtitles'], ensure_ascii=False),
                video_id
            ))
            
            conn.commit()
            logger.info(f"保存了视频 {video_id} 的 {len(subtitles_data['subtitles'])} 条字幕到JSON字段")
    
    async def process_channel_batch(self, channel_url: str, 
                                   max_videos: int = 50, subtitle_lang: str = "en", 
                                   cookie_string: Optional[str] = None) -> Dict:
        """
        批量处理频道视频（异步串行处理）
        
        Args:
            channel_url: YouTube频道URL
            max_videos: 最大视频数量
            subtitle_lang: 字幕语言
            cookie_string: 可选的cookie字符串，自动转换为Netscape格式
            
        Returns:
            处理结果统计
        """
        start_time = datetime.now()
        logger.info(f"开始批量处理频道: {channel_url}")
        
        try:
            # 1. 获取频道视频列表
            logger.info("正在获取频道视频列表...")
            channel_info, videos = self.get_channel_videos(channel_url, max_videos, cookie_string)
            
            # 2. 保存频道和视频信息
            self.save_channel_and_videos(channel_info, videos)
            
            # 3. 串行处理每个视频的字幕提取
            success_count = 0
            failed_count = 0
            
            logger.info(f"开始串行处理 {len(videos)} 个视频的字幕...")
            
            for i, video in enumerate(videos, 1):
                logger.info(f"处理进度 {i}/{len(videos)}: {video['title'][:50]}...")
                
                # 检查是否已经提取过字幕
                with sqlite3.connect(self.db_path) as conn:
                    cursor = conn.cursor()
                    cursor.execute('SELECT subtitle_extracted FROM videos WHERE video_id = ?', 
                                 (video['video_id'],))
                    result = cursor.fetchone()
                    
                    if result and result[0]:
                        logger.info(f"视频 {video['video_id']} 字幕已存在，跳过")
                        success_count += 1
                        continue
                
                # 提取字幕
                subtitles_data = self.extract_video_subtitles(
                    video['video_id'], 
                    video['url'], 
                    subtitle_lang,
                    cookie_string
                )
                
                if subtitles_data:
                    self.save_subtitles(subtitles_data, video['video_id'])
                    success_count += 1
                else:
                    failed_count += 1
                
                # 添加延迟避免请求过于频繁
                await asyncio.sleep(2)
            
            end_time = datetime.now()
            duration = (end_time - start_time).total_seconds()
            
            result = {
                'status': 'completed',
                'channel_info': channel_info,
                'total_videos': len(videos),
                'success_count': success_count,
                'failed_count': failed_count,
                'duration_seconds': duration,
                'processed_at': end_time.isoformat()
            }
            
            logger.info(f"批量处理完成: 成功 {success_count}, 失败 {failed_count}, 耗时 {duration:.1f}秒")
            return result
            
        except Exception as e:
            logger.error(f"批量处理失败: {str(e)}")
            raise
    
    def get_db_connection(self):
        """获取数据库连接"""
        import sqlite3
        return sqlite3.connect(self.db_path)
    
    def get_channel_stats(self, channel_id: str = None) -> Dict:
        """
        获取频道统计信息
        
        Args:
            channel_id: 频道ID，如果为None则返回所有频道统计
            
        Returns:
            统计信息
        """
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            
            if channel_id:
                # 单个频道统计
                cursor.execute('''
                    SELECT 
                        c.channel_name,
                        c.channel_url,
                        c.last_processed,
                        COUNT(v.id) as total_videos,
                        SUM(CASE WHEN v.subtitle_extracted THEN 1 ELSE 0 END) as videos_with_subtitles
                    FROM channels c
                    LEFT JOIN videos v ON c.channel_id = v.channel_id
                    WHERE c.channel_id = ?
                    GROUP BY c.channel_id
                ''', (channel_id,))
                
                result = cursor.fetchone()
                if result:
                    return {
                        'channel_name': result[0],
                        'channel_url': result[1],
                        'last_processed': result[2],
                        'total_videos': result[3],
                        'videos_with_subtitles': result[4]
                    }
                else:
                    return {}
            else:
                # 所有频道统计
                cursor.execute('''
                    SELECT 
                        COUNT(DISTINCT c.channel_id) as total_channels,
                        COUNT(v.id) as total_videos,
                        SUM(CASE WHEN v.subtitle_extracted THEN 1 ELSE 0 END) as videos_with_subtitles
                    FROM channels c
                    LEFT JOIN videos v ON c.channel_id = v.channel_id
                ''')
                
                result = cursor.fetchone()
                return {
                    'total_channels': result[0] or 0,
                    'total_videos': result[1] or 0,
                    'videos_with_subtitles': result[2] or 0
                }


# 全局处理器实例，供FastAPI使用
_processor_instance = None

def get_processor():
    """获取处理器实例（单例模式）"""
    global _processor_instance
    if _processor_instance is None:
        _processor_instance = YouTubeChannelProcessor()
    return _processor_instance