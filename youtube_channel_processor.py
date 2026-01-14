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
import os
BASE_DIR = Path(__file__).parent.absolute()
DB_PATH = Path(os.getenv("DB_PATH", str(BASE_DIR / "youtube_channels.db")))
COOKIE_DIR = Path(os.getenv("COOKIES_DIR", str(BASE_DIR / "cookies")))
DOWNLOADS_DIR = Path(os.getenv("DOWNLOADS_DIR", str(BASE_DIR / "downloads")))


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
                    view_count INTEGER,
                    FOREIGN KEY (channel_id) REFERENCES channels (channel_id)
                )
            ''')

            # 创建 RSS Feed 表
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS rss_feeds (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    url TEXT UNIQUE NOT NULL,
                    name TEXT NOT NULL,
                    last_fetched TIMESTAMP
                )
            ''')
            
            # 创建 RSS 文章表
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS rss_articles (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    feed_url TEXT NOT NULL,
                    title TEXT NOT NULL,
                    url TEXT UNIQUE NOT NULL,
                    summary TEXT,
                    content TEXT,
                    published_at TIMESTAMP,
                    FOREIGN KEY (feed_url) REFERENCES rss_feeds (url)
                )
            ''')
            
            # 创建索引
            cursor.execute('CREATE INDEX IF NOT EXISTS idx_videos_channel_id ON videos (channel_id)')
            cursor.execute('CREATE INDEX IF NOT EXISTS idx_videos_upload_date ON videos (upload_date)')
            cursor.execute('CREATE INDEX IF NOT EXISTS idx_videos_subtitle_extracted ON videos (subtitle_extracted)')
            cursor.execute('CREATE INDEX IF NOT EXISTS idx_rss_articles_feed_url ON rss_articles (feed_url)')
            cursor.execute('CREATE INDEX IF NOT EXISTS idx_rss_articles_published_at ON rss_articles (published_at)')
            
            # 尝试添加 view_count 列（如果表已存在但由于旧版本缺失该列）
            try:
                cursor.execute('ALTER TABLE videos ADD COLUMN view_count INTEGER')
            except sqlite3.OperationalError:
                # 列可能已经存在，忽略错误
                pass

            conn.commit()
            logger.info("数据库初始化完成（包含 RSS 表和 view_count 字段）")
    
    def get_channel_videos(self, channel_url: str, max_videos: int = 50, 
                           cookie_string: Optional[str] = None,
                           cookie_file: Optional[Path] = None) -> Tuple[Dict, List[Dict]]:
        """
        获取频道最新视频列表
        
        Args:
            channel_url: YouTube频道URL
            max_videos: 最大视频数量
            cookie_string: 可选的cookie字符串
            cookie_file: 可选的cookie文件路径
            
        Returns:
            (channel_info, videos_list)
        """
        # 配置yt-dlp选项
        ydl_opts = {
            'quiet': True,
            'no_warnings': True,
            'playlistend': max_videos,
            'extractor_args': {
                'youtubetab': {
                    'skip': ['authcheck']
                }
            },
            # 模拟现代浏览器 UA，配合 Cookie 使用效果更好
            'user_agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
        }
        
        # 处理Cookie
        temp_cookie_file = None
        if cookie_file:
            ydl_opts['cookiefile'] = str(cookie_file)
            logger.info(f"使用指定的Cookie文件: {cookie_file.name}")
        elif cookie_string:
            # 使用传入的cookie字符串，转换为Netscape格式
            temp_cookie_file = save_cookie_string_as_netscape(cookie_string)
            ydl_opts['cookiefile'] = str(temp_cookie_file)
            logger.info("使用传入的Cookie字符串（已转换为Netscape格式）")
            # 使用默认的cookie文件
            default_cookie = (COOKIE_DIR / "cookies.txt").absolute()
            if default_cookie.exists():
                ydl_opts['cookiefile'] = str(default_cookie)
                logger.info(f"使用默认Cookie文件: {default_cookie}")
            else:
                logger.warning(f"未找到默认 cookies.txt (预期路径: {default_cookie})，可能会遇到访问限制")
        
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
                            'uploader': entry.get('uploader') or channel_info['channel_name'],
                            'view_count': entry.get('view_count')
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
            
            # 保存视频信息 (使用 UPSERT 逻辑更新元数据)
            for video in videos:
                cursor.execute('''
                    INSERT INTO videos 
                    (video_id, channel_id, title, url, duration, upload_date, uploader, subtitle_extracted, subtitle_language, subtitle_json, view_count)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(video_id) DO UPDATE SET
                        title = excluded.title,
                        url = excluded.url,
                        duration = excluded.duration,
                        upload_date = excluded.upload_date,
                        uploader = excluded.uploader,
                        view_count = excluded.view_count
                ''', (
                    video['video_id'],
                    channel_info['channel_id'],
                    video['title'],
                    video['url'],
                    video['duration'],
                    video['upload_date'],
                    video['uploader'],
                    False,  # 初始值，但在 CONFLICT 时不会被覆盖
                    None,   # 初始值，但在 CONFLICT 时不会被覆盖
                    None,   # 初始值，但在 CONFLICT 时不会被覆盖
                    video.get('view_count')
                ))
            
            conn.commit()
            logger.info(f"保存了频道 '{channel_info['channel_name']}' 和 {len(videos)} 个视频")
    
    def extract_video_subtitles(self, video_id: str, video_url: str, 
                               subtitle_lang: str = "en", 
                               cookie_string: Optional[str] = None,
                               cookie_file: Optional[Path] = None) -> Optional[List[Dict]]:
        """
        提取单个视频的字幕
        
        Args:
            video_id: 视频ID
            video_url: 视频URL
            subtitle_lang: 字幕语言
            cookie_string: 可选的cookie字符串
            cookie_file: 可选的cookie文件路径
            
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
            # 保持 UA 一致，防止风控
            'user_agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
        }
        
        # 处理Cookie
        temp_cookie_file = None
        if cookie_file:
            ydl_opts['cookiefile'] = str(cookie_file)
        elif cookie_string:
            # 使用传入的cookie字符串，转换为Netscape格式
            temp_cookie_file = save_cookie_string_as_netscape(cookie_string)
            ydl_opts['cookiefile'] = str(temp_cookie_file)
        else:
            # 使用默认的cookie文件
            default_cookie = COOKIE_DIR / "cookies.txt"
            if default_cookie.exists():
                ydl_opts['cookiefile'] = str(default_cookie)
        
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
                                   cookie_string: Optional[str] = None,
                                   cookie_file: Optional[Path] = None) -> Dict:
        """
        批量处理频道视频（异步串行处理）
        
        Args:
            channel_url: YouTube频道URL
            max_videos: 最大视频数量
            subtitle_lang: 字幕语言
            cookie_string: 可选的cookie字符串
            cookie_file: 可选的cookie文件路径
            
        Returns:
            处理结果统计
        """
        start_time = datetime.now()
        logger.info(f"开始批量处理频道: {channel_url}")
        
        try:
            # 1. 获取频道视频列表
            logger.info("正在获取频道视频列表...")
            channel_info, videos = self.get_channel_videos(channel_url, max_videos, cookie_string, cookie_file)
            
            # 2. 保存频道和视频信息
            self.save_channel_and_videos(channel_info, videos)
            
            # 3. 串行处理每个视频的字幕提取
            # 3. 串行处理每个视频的字幕提取
            success_count = 0
            failed_count = 0
            skipped_count = 0
            downloaded_count = 0
            
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
                        skipped_count += 1
                        continue
                
                # 提取字幕
                subtitles_data = self.extract_video_subtitles(
                    video['video_id'], 
                    video['url'], 
                    subtitle_lang,
                    cookie_string,
                    cookie_file
                )
                
                if subtitles_data:
                    self.save_subtitles(subtitles_data, video['video_id'])
                    success_count += 1
                    downloaded_count += 1
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
                'skipped_count': skipped_count,
                'downloaded_count': downloaded_count,
                'duration_seconds': duration,
                'processed_at': end_time.isoformat()
            }
            
            logger.info(f"批量处理完成: 成功 {success_count} (下载: {downloaded_count}, 跳过: {skipped_count}), 失败 {failed_count}, 耗时 {duration:.1f}秒")
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

    def get_oldest_channel(self) -> Optional[Dict]:
        """
        获取更新时间最早（最后一次处理时间最久）的一个频道
        
        Returns:
            频道信息字典，如果不存在则返回None
        """
        with sqlite3.connect(self.db_path) as conn:
            # 修改查询以支持 JSON 模式
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()
            
            # 优先选择 last_processed 为空的，然后按 last_processed 升序排列
            cursor.execute('''
                SELECT channel_id, channel_name, channel_url, last_processed
                FROM channels
                ORDER BY last_processed ASC NULLS FIRST
                LIMIT 1
            ''')
            
            row = cursor.fetchone()
            if row:
                return dict(row)
            return None

    def get_random_video_for_subtitle_update(self) -> Optional[Dict]:
        """
        获取一个随机视频用于字幕更新（优先选择没有字幕的视频）
        
        Returns:
            视频信息字典，如果不存在则返回None
        """
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()
            
            # 优先选择没有字幕的视频，如果都有字幕则随机选择一个
            cursor.execute('''
                SELECT video_id, title, url, channel_id, subtitle_extracted
                FROM videos
                WHERE subtitle_extracted = 0 OR subtitle_extracted IS NULL
                ORDER BY RANDOM()
                LIMIT 1
            ''')
            
            row = cursor.fetchone()
            if row:
                return dict(row)
            
            # 如果所有视频都有字幕，则随机选择一个视频重新更新字幕
            cursor.execute('''
                SELECT video_id, title, url, channel_id, subtitle_extracted
                FROM videos
                ORDER BY RANDOM()
                LIMIT 1
            ''')
            
            row = cursor.fetchone()
            if row:
                return dict(row)
            
            return None


# 全局处理器实例，供FastAPI使用
_processor_instance = None

def get_processor():
    """获取处理器实例（单例模式）"""
    global _processor_instance
    if _processor_instance is None:
        _processor_instance = YouTubeChannelProcessor()
    return _processor_instance