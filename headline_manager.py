"""
Headline Manager - 处理 D1 数据库中的 AI Headlines 操作
"""
import uuid
import time
import json
import logging
from typing import List, Dict, Optional
from d1_client import D1Client

logger = logging.getLogger(__name__)


class HeadlineManager:
    """AI标题管理器"""
    
    def __init__(self):
        self.d1 = D1Client()
    
    def insert_headline(self, user_id: str, title: str, content: str, 
                       article_count: int, prompt: str = None, 
                       feed_ids: str = None, slides: List[Dict] = None,
                       created_at: int = None,
                       is_scheduled: bool = False,
                       scheduled_task_id: str = None) -> str:
        """
        插入AI生成的标题到数据库
        
        Args:
            user_id: 用户ID
            title: 标题
            content: 内容（JSON字符串，格式：{"html": string, "citedFeeds": array, "citedArticles": array}）
            article_count: 文章数量
            prompt: 提示词
            feed_ids: Feed IDs（逗号分隔或JSON）
            slides: 幻灯片列表
            created_at: 创建时间戳（毫秒），None则使用当前时间
            is_scheduled: 是否为定时任务生成的
            scheduled_task_id: 定时任务ID
        
        Returns:
            headline_id: 创建的标题ID
        """
        try:
            headline_id = str(uuid.uuid4())
            
            if created_at is None:
                created_at = int(time.time() * 1000)
            
            # 序列化幻灯片
            slides_json = json.dumps(slides) if slides else None
            
            # 尝试 snake_case (用于 inspilot-db 等新版 D1)
            try:
                self.d1.execute("""
                    INSERT INTO ai_headlines 
                    (id, user_id, title, content, article_count, prompt, feed_ids, slides, created_at, is_scheduled, scheduled_task_id)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, [
                    headline_id, user_id, title, content, article_count, 
                    prompt or '', feed_ids or '', slides_json, created_at,
                    1 if is_scheduled else 0, scheduled_task_id
                ])
                logger.info(f"成功插入AI标题 (snake_case): {headline_id}")
            except Exception as e_snake:
                # 尝试 camelCase (用于 inspilot 等老版 D1)
                try:
                    self.d1.execute("""
                        INSERT INTO ai_headlines 
                        (id, userId, title, content, articleCount, prompt, feedIds, slides, createdAt, isScheduled, scheduledTaskId)
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """, [
                        headline_id, user_id, title, content, article_count, 
                        prompt or '', feed_ids or '', slides_json, created_at,
                        1 if is_scheduled else 0, scheduled_task_id
                    ])
                    logger.info(f"成功插入AI标题 (camelCase): {headline_id}")
                except Exception as e_camel:
                    logger.error(f"插入AI标题失败 (尝试了 snake_case 和 camelCase): {e_snake} | {e_camel}")
                    raise
            
            return headline_id
            
        except Exception as e:
            logger.error(f"插入AI标题失败: {e}")
            raise
    
    def get_headline_by_id(self, headline_id: str) -> Optional[Dict]:
        """根据ID获取标题"""
        try:
            headline = self.d1.fetch_one(
                "SELECT * FROM ai_headlines WHERE id = ?", 
                [headline_id]
            )
            
            if headline:
                # 反序列化幻灯片
                if headline.get('slides'):
                    try:
                        headline['slides'] = json.loads(headline['slides'])
                    except:
                        headline['slides'] = []
                logger.info(f"获取到标题: {headline_id}")
            else:
                logger.warning(f"未找到标题: {headline_id}")
            
            return headline
        except Exception as e:
            logger.error(f"获取标题 {headline_id} 失败: {e}")
            return None
    
    def get_headlines_by_user(self, user_id: str, limit: int = 50) -> List[Dict]:
        """
        获取用户的AI标题列表
        
        Args:
            user_id: 用户ID
            limit: 限制数量
        
        Returns:
            标题列表
        """
        try:
            headlines = self.d1.fetch_all(
                "SELECT * FROM ai_headlines WHERE userId = ? ORDER BY createdAt DESC LIMIT ?",
                [user_id, limit]
            )
            
            # 反序列化幻灯片
            for headline in headlines:
                if headline.get('slides'):
                    try:
                        headline['slides'] = json.loads(headline['slides'])
                    except:
                        headline['slides'] = []
            
            logger.info(f"用户 {user_id} 有 {len(headlines)} 个标题")
            return headlines
        except Exception as e:
            logger.error(f"获取用户 {user_id} 的标题失败: {e}")
            return []
    
    def get_recent_headlines(self, limit: int = 10) -> List[Dict]:
        """获取最近的标题"""
        try:
            headlines = self.d1.fetch_all(
                "SELECT * FROM ai_headlines ORDER BY createdAt DESC LIMIT ?",
                [limit]
            )
            
            # 反序列化幻灯片
            for headline in headlines:
                if headline.get('slides'):
                    try:
                        headline['slides'] = json.loads(headline['slides'])
                    except:
                        headline['slides'] = []
            
            logger.info(f"获取到 {len(headlines)} 个最近标题")
            return headlines
        except Exception as e:
            logger.error(f"获取最近标题失败: {e}")
            return []
    
    def update_headline(self, headline_id: str, title: str = None, 
                       content: str = None, slides: List[Dict] = None) -> bool:
        """
        更新标题
        
        Args:
            headline_id: 标题ID
            title: 新标题（可选）
            content: 新内容（可选）
            slides: 新幻灯片（可选）
        
        Returns:
            是否成功
        """
        try:
            updates = []
            params = []
            
            if title is not None:
                updates.append("title = ?")
                params.append(title)
            
            if content is not None:
                updates.append("content = ?")
                params.append(content)
            
            if slides is not None:
                updates.append("slides = ?")
                params.append(json.dumps(slides))
            
            if not updates:
                logger.warning(f"更新标题 {headline_id} 时没有提供任何更新字段")
                return False
            
            params.append(headline_id)
            sql = f"UPDATE ai_headlines SET {', '.join(updates)} WHERE id = ?"
            
            self.d1.execute(sql, params)
            logger.info(f"成功更新标题: {headline_id}")
            return True
            
        except Exception as e:
            logger.error(f"更新标题 {headline_id} 失败: {e}")
            return False
    
    def delete_headline(self, headline_id: str) -> bool:
        """删除标题"""
        try:
            self.d1.execute("DELETE FROM ai_headlines WHERE id = ?", [headline_id])
            logger.info(f"成功删除标题: {headline_id}")
            return True
        except Exception as e:
            logger.error(f"删除标题 {headline_id} 失败: {e}")
            return False
    
    def get_headlines_by_feed(self, feed_ids: str, limit: int = 10) -> List[Dict]:
        """
        根据Feed ID获取标题
        
        Args:
            feed_ids: Feed IDs（逗号分隔）
            limit: 限制数量
        
        Returns:
            标题列表
        """
        try:
            # 使用 LIKE 查询，因为 feedIds 是逗号分隔的字符串
            headlines = self.d1.fetch_all(
                "SELECT * FROM ai_headlines WHERE feedIds LIKE ? ORDER BY createdAt DESC LIMIT ?",
                [f"%{feed_ids}%", limit]
            )
            
            # 反序列化幻灯片
            for headline in headlines:
                if headline.get('slides'):
                    try:
                        headline['slides'] = json.loads(headline['slides'])
                    except:
                        headline['slides'] = []
            
            logger.info(f"Feed {feed_ids} 有 {len(headlines)} 个标题")
            return headlines
        except Exception as e:
            logger.error(f"获取 Feed {feed_ids} 的标题失败: {e}")
            return []
    
    def get_statistics(self, user_id: str = None) -> Dict:
        """
        获取统计信息
        
        Args:
            user_id: 用户ID（可选，None则获取全局统计）
        
        Returns:
            统计信息字典
        """
        try:
            if user_id:
                total = self.d1.fetch_one(
                    "SELECT COUNT(*) as count, SUM(articleCount) as total_articles FROM ai_headlines WHERE userId = ?",
                    [user_id]
                )
            else:
                total = self.d1.fetch_one(
                    "SELECT COUNT(*) as count, SUM(articleCount) as total_articles FROM ai_headlines"
                )
            
            stats = {
                "total_headlines": total.get('count', 0) if total else 0,
                "total_articles_processed": total.get('total_articles', 0) if total else 0,
            }
            
            logger.info(f"统计信息: {stats}")
            return stats
            
        except Exception as e:
            logger.error(f"获取统计信息失败: {e}")
            return {
                "total_headlines": 0,
                "total_articles_processed": 0,
            }


# 全局实例
_headline_manager_instance = None


def get_headline_manager() -> HeadlineManager:
    """获取标题管理器实例（单例模式）"""
    global _headline_manager_instance
    if _headline_manager_instance is None:
        _headline_manager_instance = HeadlineManager()
    return _headline_manager_instance
