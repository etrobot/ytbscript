"""
Data Fetcher - 从本地数据库获取数据（视频字幕、RSS文章等）
"""
import json
import logging
import feedparser
import sqlite3
import time
from typing import List, Dict, Optional, Any
from d1_client import D1Client
from datetime import datetime, timedelta
from youtube_channel_processor import get_processor

logger = logging.getLogger(__name__)


class DataFetcher:
    """数据获取器"""
    
    def __init__(self):
        self.processor = get_processor()
        self.d1 = D1Client()
    
    async def fetch_channel_subtitles(self, channel_id: str):
        """获取频道的字幕数据"""
        channel_url = f"https://www.youtube.com/channel/{channel_id}"
        logger.info(f"获取频道视频: {channel_id}")
        try:
            result = await self.processor.process_channel_batch(channel_url, max_videos=5)
            return result
        except Exception as e:
            logger.error(f"处理频道 {channel_id} 失败: {e}")
            return None
    
    async def get_recent_videos(self, channel_ids: List[str], days: int = 7, 
                               max_videos_per_channel: int = 10) -> List[Dict]:
        """
        获取最近的视频数据
        
        Args:
            channel_ids: 频道ID列表
            days: 获取多少天内的视频（默认7天）
            max_videos_per_channel: 每个频道最多获取多少视频（默认10个）
        
        Returns:
            视频文章列表，格式与articles一致
        """
        MAX_ARTICLES = 30
        
        # 注意：自动获取逻辑已移至 execute_d1_task.py
        
        articles = []
        
        with self.processor.get_db_connection() as conn:
            cursor = conn.cursor()
            
            # 计算日期阈值 (使用 YYYYMMDD 格式以匹配本地数据库)
            since_date = datetime.now() - timedelta(days=days)
            since_date_str = since_date.strftime('%Y%m%d')
            
            for cid in channel_ids:
                # 获取最近的视频
                cursor.execute("""
                    SELECT v.video_id, v.title, v.subtitle_json, v.upload_date, 
                           c.channel_name, v.url, v.view_count
                    FROM videos v 
                    JOIN channels c ON v.channel_id = c.channel_id 
                    WHERE c.channel_id = ? 
                        AND v.subtitle_extracted = 1
                        AND v.upload_date >= ?
                    ORDER BY v.upload_date DESC 
                    LIMIT ?
                """, (cid.strip(), since_date_str, max_videos_per_channel))
                
                rows = cursor.fetchall()
                for video_id, title, subtitle_json_str, upload_date, channel_name, url, view_count in rows:
                    if not subtitle_json_str:
                        continue
                    
                    try:
                        subtitles = json.loads(subtitle_json_str)
                        transcript_text = " ".join([s.get('subtitle', '') for s in subtitles])
                        
                        # 创建类似文章的结构
                        articles.append({
                            'id': video_id,  # 使用 video_id 作为唯一标识
                            'title': title,
                            'summary': '',
                            'content': '',
                            'videoTranscript': transcript_text,
                            'url': url or f"https://www.youtube.com/watch?v={video_id}",
                            'feedId': cid.strip(),  # 使用 channel_id 作为 feedId
                            'feedName': channel_name or 'YouTube Channel',
                            'feedIcon': f"https://www.youtube.com/channel/{cid.strip()}",  # YouTube 频道链接
                            'imageUrl': f"https://img.youtube.com/vi/{video_id}/maxresdefault.jpg",  # 视频缩略图
                            'publishedAt': upload_date,
                            'videoViews': view_count
                        })
                    except Exception as e:
                        logger.error(f"解析字幕失败 {title}: {e}")
        
        # 按日期排序（最新的在前）并限制数量
        articles.sort(key=lambda x: x.get('publishedAt', ''), reverse=True)
        result = articles[:MAX_ARTICLES]
        
        logger.info(f"获取到 {len(result)} 个视频（从 {len(channel_ids)} 个频道，{days} 天内）")
        return result
    
    def get_videos_by_ids(self, video_ids: List[str]) -> List[Dict]:
        """
        根据视频ID列表获取视频数据
        
        Args:
            video_ids: 视频ID列表
        
        Returns:
            视频文章列表
        """
        if not video_ids:
            return []
        
        articles = []
        
        with self.processor.get_db_connection() as conn:
            cursor = conn.cursor()
            
            placeholders = ','.join('?' * len(video_ids))
            cursor.execute(f"""
                SELECT v.video_id, v.title, v.subtitle_json, v.upload_date, 
                       c.channel_name, c.channel_id, v.url, v.view_count
                FROM videos v 
                JOIN channels c ON v.channel_id = c.channel_id 
                WHERE v.video_id IN ({placeholders})
                    AND v.subtitle_extracted = 1
                ORDER BY v.upload_date DESC
            """, video_ids)
            
            rows = cursor.fetchall()
            for video_id, title, subtitle_json_str, upload_date, channel_name, channel_id, url, view_count in rows:
                if not subtitle_json_str:
                    continue
                
                try:
                    subtitles = json.loads(subtitle_json_str)
                    transcript_text = " ".join([s.get('subtitle', '') for s in subtitles])
                    
                    articles.append({
                        'id': video_id,  # 使用 video_id 作为唯一标识
                        'title': title,
                        'summary': '',
                        'content': '',
                        'videoTranscript': transcript_text,
                        'url': url or f"https://www.youtube.com/watch?v={video_id}",
                        'feedId': channel_id,  # 使用 channel_id 作为 feedId
                        'feedName': channel_name or 'YouTube Channel',
                        'feedIcon': f"https://www.youtube.com/channel/{channel_id}" if channel_id else None,
                        'imageUrl': f"https://img.youtube.com/vi/{video_id}/maxresdefault.jpg",
                        'publishedAt': upload_date,
                        'videoViews': view_count
                    })
                except Exception as e:
                    logger.error(f"解析字幕失败 {title}: {e}")
        
        logger.info(f"根据ID获取到 {len(articles)} 个视频")
        return articles


    async def fetch_and_save_rss_articles(self, url: str, name: str = None) -> int:
        """
        抓取并解析 RSS Feed，保存到本地数据库
        """
        logger.info(f"正在抓取 RSS Feed: {url}")
        try:
            feed = feedparser.parse(url)
            if not feed.entries:
                logger.warning(f"Feed {url} 没有条目")
                return 0
            
            feed_name = name or feed.feed.get('title', url)
            
            with self.processor.get_db_connection() as conn:
                cursor = conn.cursor()
                
                # 更新或插入 Feed 信息
                cursor.execute("""
                    INSERT INTO rss_feeds (url, name, last_fetched)
                    VALUES (?, ?, ?)
                    ON CONFLICT(url) DO UPDATE SET 
                        name = excluded.name,
                        last_fetched = excluded.last_fetched
                """, (url, feed_name, int(time.time() * 1000)))
                
                count = 0
                for entry in feed.entries:
                    title = entry.get('title', '无标题')
                    link = entry.get('link', '')
                    summary = entry.get('summary', '')
                    content = ""
                    if 'content' in entry:
                        content = entry.content[0].value
                    elif 'description' in entry:
                        content = entry.description
                        
                    published_at = None
                    if 'published_parsed' in entry and entry.published_parsed:
                        published_at = int(time.mktime(entry.published_parsed) * 1000)
                    elif 'updated_parsed' in entry and entry.updated_parsed:
                        published_at = int(time.mktime(entry.updated_parsed) * 1000)
                    else:
                        published_at = int(time.time() * 1000)
                        
                    try:
                        cursor.execute("""
                            INSERT INTO rss_articles (feed_url, title, url, summary, content, published_at)
                            VALUES (?, ?, ?, ?, ?, ?)
                            ON CONFLICT(url) DO NOTHING
                        """, (url, title, link, summary, content, published_at))
                        if cursor.rowcount > 0:
                            count += 1
                    except Exception as e:
                        logger.error(f"保存文章失败 {title}: {e}")
                
                conn.commit()
                logger.info(f"Feed {feed_name} 处理完成，新增 {count} 篇文章")
                return count
        except Exception as e:
            logger.error(f"抓取 RSS Feed {url} 失败: {e}")
            return 0

    async def get_recent_rss_articles(self, feed_urls: List[str], days: int = 7, limit_per_feed: int = 10) -> List[Dict]:
        """
        从本地数据库获取最近的文章
        """
        if not feed_urls:
            return []
            
        articles = []
        since_timestamp = int((datetime.now() - timedelta(days=days)).timestamp() * 1000)
        
        with self.processor.get_db_connection() as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()
            
            for url in feed_urls:
                try:
                    # 先尝试更新
                    await self.fetch_and_save_rss_articles(url)
                    
                    # 获取 feed 名称
                    cursor.execute("SELECT name FROM rss_feeds WHERE url = ?", [url])
                    row = cursor.fetchone()
                    feed_name = row['name'] if row else 'Unknown RSS'
                    
                    # 获取文章
                    cursor.execute("""
                        SELECT id, title, summary, content, url, published_at 
                        FROM rss_articles 
                        WHERE feed_url = ? AND published_at >= ?
                        ORDER BY published_at DESC 
                        LIMIT ?
                    """, [url, since_timestamp, limit_per_feed])
                    
                    rows = cursor.fetchall()
                    for row in rows:
                        articles.append({
                            'id': str(row['id']),  # 使用数据库 id 作为唯一标识
                            'title': row['title'],
                            'summary': row['summary'],
                            'content': row['content'],
                            'videoTranscript': row['content'] or row['summary'],
                            'url': row['url'],
                            'feedId': url,  # 使用 feed URL 作为 feedId
                            'feedName': feed_name,
                            'feedIcon': None,  # RSS 没有图标
                            'imageUrl': None,  # RSS 文章没有默认图片
                            'publishedAt': row['published_at'],
                            'videoViews': None
                        })
                except Exception as e:
                    logger.error(f"获取本地 RSS Feed {url} 失败: {e}")
                    
        return articles


# 全局实例
_data_fetcher_instance = None


def get_data_fetcher() -> DataFetcher:
    """获取数据获取器实例（单例模式）"""
    global _data_fetcher_instance
    if _data_fetcher_instance is None:
        _data_fetcher_instance = DataFetcher()
    return _data_fetcher_instance
