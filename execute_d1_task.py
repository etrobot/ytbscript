"""
执行生产 D1 任务脚本
作为执行引擎供 scheduler_service 调用，也可通过命令行手动触发。
"""
import asyncio
import os
import sys
import json
import logging
import time
import re
from typing import Dict, Any, List
from dotenv import load_dotenv

# 加载环境变量
load_dotenv()

# 配置日志
logger = logging.getLogger(__name__)

# 导入工具模块
from d1_task_manager import get_task_manager
from data_fetcher import get_data_fetcher
from ai_generator import get_ai_generator
from headline_manager import get_headline_manager
from youtube_channel_processor import get_processor
from d1_client import D1Client

def resolve_feed_urls_to_channel_ids(feed_urls: List[str]) -> Dict[str, Dict[str, str]]:
    """解析 feed URL 列表到 YouTube 频道 ID 或 RSS Feed"""
    result = {}
    for url in feed_urls:
        try:
            # 1. YouTube 频道
            match = re.search(r'channel_id=([A-Za-z0-9_-]+)', url)
            if match:
                channel_id = match.group(1)
                result[url] = {"channel_id": channel_id, "name": channel_id, "url": url, "type": "youtube"}
                continue
            if 'youtube.com/@' in url:
                name = url.split('@')[-1].split('/')[0]
                result[url] = {"channel_id": f"@{name}", "name": f"@{name}", "url": url, "type": "youtube"}
                continue
            elif 'youtube.com/channel/' in url:
                channel_id = url.split('channel/')[-1].split('/')[0]
                result[url] = {"channel_id": channel_id, "name": channel_id, "url": url, "type": "youtube"}
                continue
            
            # 2. RSS Feed (默认除 YouTube 外均为 RSS)
            result[url] = {"feed_id": None, "name": url, "url": url, "type": "rss"}
        except Exception as e:
            logger.error(f"解析 URL {url} 失败: {e}")
    return result

def resolve_feed_ids_to_channel_ids(feed_ids: List[str]) -> Dict[str, Dict[str, str]]:
    """从 feed ID 列表解析 (主要处理 UC 开头的 YouTube 频道 ID)"""
    result = {}
    for feed_id in feed_ids:
        try:
            if feed_id.startswith('UC') and len(feed_id) == 24:
                result[feed_id] = {"channel_id": feed_id, "name": feed_id, "url": f"https://www.youtube.com/channel/{feed_id}", "type": "youtube"}
                continue
            # 不再从 D1 feeds 表查询 RSS，如果没有明确 URL，RSS 需要通过 resolve_feed_urls_to_channel_ids
        except Exception as e:
            logger.error(f"解析 feed {feed_id} 失败: {e}")
    return result

async def fetch_missing_subtitles(processor, channel_ids: List[str]):
    """检查并获取缺失的字幕数据"""
    from cookie_keepalive_service import get_keepalive_service
    from pathlib import Path
    
    logger.info(f"检查 {len(channel_ids)} 个频道的字幕数据...")
    
    cookie_dir = Path(__file__).parent / "cookies"
    keepalive_service = get_keepalive_service(cookie_dir=cookie_dir)
    fetched_count = 0
    
    with processor.get_db_connection() as conn:
        cursor = conn.cursor()
        for channel_id in channel_ids:
            cursor.execute("SELECT c.channel_id, c.channel_name, SUM(CASE WHEN v.subtitle_extracted = 1 THEN 1 ELSE 0 END) as subtitle_count FROM channels c LEFT JOIN videos v ON c.channel_id = v.channel_id WHERE c.channel_id = ? GROUP BY c.channel_id", (channel_id,))
            row = cursor.fetchone()
            
            if not row:
                logger.info(f"  频道 {channel_id[:8]}... 不在数据库中，开始抓取...")
                subtitle_count = 0
            else:
                subtitle_count = row[2] or 0
                logger.info(f"  频道 {channel_id[:8]}... ({row[1]}) 已有 {subtitle_count} 个字幕")
            
            if not row or subtitle_count == 0:
                cookie_info = keepalive_service.get_active_cookie()
                if not cookie_info:
                    logger.warning(f"  跳过 {channel_id[:8]}...: 没有可用的cookie")
                    continue
                    
                _, cookie_path = cookie_info
                logger.info(f"  开始抓取频道 {channel_id[:8]}... (max 5 videos)...")
                
                try:
                    result = await processor.process_channel_batch(
                        f"https://www.youtube.com/channel/{channel_id}", 
                        max_videos=5, 
                        cookie_file=cookie_path
                    )
                    fetched_count += 1
                    logger.info(f"  ✓ 频道 {channel_id[:8]}... 抓取完成")
                except Exception as e:
                    logger.error(f"  ✗ 频道 {channel_id[:8]}... 抓取失败: {e}")
    
    if fetched_count > 0:
        logger.info(f"字幕抓取完成: {fetched_count}/{len(channel_ids)} 个频道")
    else:
        logger.info(f"无需抓取字幕（已有数据或无可用cookie）")
    
    return fetched_count

async def execute_task(task_id: str, scheduled_timestamp: int = None):
    """执行指定的 D1 任务"""
    logger.info(f"开始执行任务: {task_id}")
    try:
        task_manager = get_task_manager()
        task_raw = task_manager.get_task_by_id(task_id)
        if not task_raw:
            logger.error(f"找不到任务: {task_id}"); return

        task = {
            'id': task_raw.get('id'),
            'user_id': task_raw.get('user_id') or task_raw.get('userId'),
            'task_type': task_raw.get('task_type') or task_raw.get('taskType'),
            'feed_ids': task_raw.get('feed_ids') or task_raw.get('feedIds'),
            'prompt': task_raw.get('prompt'),
            'feed_urls': task_raw.get('feed_urls') or task_raw.get('feedUrls'),
        }

        # 1. 解析 Feed
        feed_mapping = {}
        feed_urls_raw = task.get('feed_urls')
        if feed_urls_raw:
            urls = json.loads(feed_urls_raw) if isinstance(feed_urls_raw, str) and feed_urls_raw.startswith('[') else ([u.strip() for u in feed_urls_raw.split(',')] if isinstance(feed_urls_raw, str) else feed_urls_raw)
            feed_mapping = resolve_feed_urls_to_channel_ids(urls)
        
        if not feed_mapping:
            ids_raw = task.get('feed_ids') or ''
            ids = json.loads(ids_raw) if isinstance(ids_raw, str) and ids_raw.startswith('[') else ([i.strip() for i in ids_raw.split(',')] if isinstance(ids_raw, str) else ids_raw)
            feed_mapping = resolve_feed_ids_to_channel_ids(ids)

        if not feed_mapping:
            logger.error("无法解析 feed 信息"); return

        youtube_channel_ids = [i['channel_id'] for i in feed_mapping.values() if i.get('type') == 'youtube' or 'channel_id' in i]
        rss_feeds = [i for i in feed_mapping.values() if i.get('type') == 'rss']
        
        # 2. 字幕检查
        if youtube_channel_ids:
            await fetch_missing_subtitles(get_processor(), list(set(youtube_channel_ids)))

        # 3. 抓取数据
        data_fetcher = get_data_fetcher()
        all_articles = []
        if youtube_channel_ids:
            all_articles.extend(await data_fetcher.get_recent_videos(list(set(youtube_channel_ids)), days=30))
        if rss_feeds:
            rss_urls = [r['url'] for r in rss_feeds]
            all_articles.extend(await data_fetcher.get_recent_rss_articles(rss_urls, days=30))
            
        if not all_articles:
            logger.warning("未找到内容数据"); return

        all_articles.sort(key=lambda x: str(x.get('publishedAt', '')), reverse=True)

        # 4. AI 生成
        ai_generator = get_ai_generator()
        prompt = task.get('prompt', '总结最新见解和趋势')
        result = await ai_generator.generate_headline(articles=all_articles, prompt=prompt, user_provided_prompt=bool(prompt and prompt.strip()))
        
        # 5. 保存（content字段存储JSON，包含html、citedFeeds和citedArticles）
        content_with_metadata = json.dumps({
            "html": result.get('content', ''),
            "citedFeeds": result.get('citedFeeds', []),
            "citedArticles": result.get('citedArticles', [])
        })
        
        headline_id = get_headline_manager().insert_headline(
            user_id=task['user_id'], title=result.get('title', ''), content=content_with_metadata,
            article_count=len(all_articles), prompt=prompt, feed_ids=task['feed_ids'] or task.get('feed_urls'),
            slides=result.get('slides', []), created_at=scheduled_timestamp, is_scheduled=True, scheduled_task_id=task['id']
        )
        
        # 6. 更新任务时间
        task_manager.update_task_execution_time(task['id'], int(time.time() * 1000))
        logger.info(f"任务执行成功！Headline ID: {headline_id}")

    except Exception as e:
        logger.error(f"执行失败: {e}", exc_info=True)

async def main():
    """手动执行所有活跃任务"""
    logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
    tasks = get_task_manager().get_active_tasks()
    if not tasks: 
        logger.info("没有活跃任务"); return
    logger.info(f"找到 {len(tasks)} 个活跃任务，准备手动执行...")
    for t in tasks:
        await execute_task(t.get('id'))

if __name__ == "__main__":
    asyncio.run(main())
