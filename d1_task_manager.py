"""
D1 Task Manager - 处理 D1 数据库中的任务操作
"""
import logging
from typing import List, Dict, Optional
from d1_client import D1Client

logger = logging.getLogger(__name__)


class D1TaskManager:
    """D1 任务管理器"""
    
    def __init__(self):
        self.d1 = D1Client()
    
    def get_active_tasks(self) -> List[Dict]:
        """获取所有活跃的任务"""
        try:
            tasks = self.d1.fetch_all("SELECT * FROM scheduled_tasks WHERE is_active = 1")
            logger.info(f"获取到 {len(tasks)} 个活跃任务")
            return tasks
        except Exception as e:
            logger.error(f"获取活跃任务失败: {e}")
            return []

    def get_all_tasks(self) -> List[Dict]:
        """获取所有任务"""
        try:
            tasks = self.d1.fetch_all("SELECT * FROM scheduled_tasks")
            logger.info(f"获取到 {len(tasks)} 个总任务")
            return tasks
        except Exception as e:
            logger.error(f"获取所有任务失败: {e}")
            return []
    
    def get_task_by_id(self, task_id: str) -> Optional[Dict]:
        """根据ID获取任务"""
        try:
            task = self.d1.fetch_one("SELECT * FROM scheduled_tasks WHERE id = ?", [task_id])
            if task:
                logger.info(f"获取到任务: {task_id}")
            else:
                logger.warning(f"未找到任务: {task_id}")
            return task
        except Exception as e:
            logger.error(f"获取任务 {task_id} 失败: {e}")
            return None
    
    def get_tasks_by_user(self, user_id: str) -> List[Dict]:
        """获取用户的所有任务"""
        try:
            tasks = self.d1.fetch_all("SELECT * FROM scheduled_tasks WHERE user_id = ?", [user_id])
            logger.info(f"用户 {user_id} 有 {len(tasks)} 个任务")
            return tasks
        except Exception as e:
            logger.error(f"获取用户 {user_id} 的任务失败: {e}")
            return []
    
    def update_task_execution_time(self, task_id: str, execution_time: int):
        """更新任务最后执行时间"""
        try:
            self.d1.execute("""
                UPDATE scheduled_tasks SET last_executed_at = ? WHERE id = ?
            """, [execution_time, task_id])
            logger.info(f"更新任务 {task_id} 执行时间: {execution_time}")
        except Exception as e:
            logger.error(f"更新任务执行时间失败: {e}")
            raise
    
    def create_task(self, user_id: str, task_type: str, scheduled_hour: int, 
                   feed_ids: str, prompt: str = None, scheduled_minute: int = 0) -> str:
        """创建新任务"""
        import uuid
        import time
        
        try:
            task_id = str(uuid.uuid4())
            now = int(time.time() * 1000)
            
            self.d1.execute("""
                INSERT INTO scheduled_tasks 
                (id, user_id, task_type, scheduled_hour, scheduled_minute, feed_ids, prompt, is_active, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, 1, ?, ?)
            """, [task_id, user_id, task_type, scheduled_hour, scheduled_minute, feed_ids, prompt, now, now])
            
            logger.info(f"创建任务成功: {task_id}")
            return task_id
        except Exception as e:
            logger.error(f"创建任务失败: {e}")
            raise
    
    def deactivate_task(self, task_id: str):
        """停用任务"""
        try:
            self.d1.execute("UPDATE scheduled_tasks SET is_active = 0 WHERE id = ?", [task_id])
            logger.info(f"任务 {task_id} 已停用")
        except Exception as e:
            logger.error(f"停用任务失败: {e}")
            raise


# 全局实例
_task_manager_instance = None


def get_task_manager() -> D1TaskManager:
    """获取任务管理器实例（单例模式）"""
    global _task_manager_instance
    if _task_manager_instance is None:
        _task_manager_instance = D1TaskManager()
    return _task_manager_instance
