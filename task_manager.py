"""
任务管理器 - 处理批量任务的异步队列
"""

import asyncio
import uuid
import json
import sqlite3
from datetime import datetime
from enum import Enum
from typing import Dict, List, Optional
from pathlib import Path
import logging
import concurrent.futures
import threading

logger = logging.getLogger(__name__)

class TaskStatus(Enum):
    PENDING = "pending"        # 等待中
    RUNNING = "running"        # 执行中
    COMPLETED = "completed"    # 已完成
    FAILED = "failed"         # 失败
    CANCELLED = "cancelled"    # 已取消

class TaskType(Enum):
    BATCH_PROCESS = "batch_process"

class TaskManager:
    """任务管理器"""
    
    def __init__(self, db_path: str = None):
        self.db_path = db_path or str(Path(__file__).parent / "youtube_channels.db")
        self.running_tasks: Dict[str, asyncio.Task] = {}
        self.init_task_tables()
    
    def init_task_tables(self):
        """初始化任务表"""
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS tasks (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    task_id TEXT UNIQUE NOT NULL,
                    task_type TEXT NOT NULL,
                    status TEXT NOT NULL,
                    params TEXT NOT NULL,
                    result TEXT,
                    error_message TEXT,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    started_at TIMESTAMP,
                    completed_at TIMESTAMP,
                    progress INTEGER DEFAULT 0,
                    total_items INTEGER DEFAULT 0,
                    current_item TEXT
                )
            ''')
            
            cursor.execute('CREATE INDEX IF NOT EXISTS idx_tasks_status ON tasks (status)')
            cursor.execute('CREATE INDEX IF NOT EXISTS idx_tasks_created ON tasks (created_at)')
            
            conn.commit()
    
    def create_task(self, task_type: TaskType, params: Dict) -> str:
        """
        创建新任务
        
        Args:
            task_type: 任务类型
            params: 任务参数
            
        Returns:
            任务ID
        
        Raises:
            ValueError: 如果发现重复的频道任务
        """
        # 检查是否已有相同频道的任务在进行中
        if task_type == TaskType.BATCH_PROCESS:
            existing_task = self._check_duplicate_channel_task(params.get('channel_url'))
            if existing_task:
                raise ValueError(f"频道 '{params.get('channel_url')}' 已有任务在处理中 (任务ID: {existing_task['task_id'][:8]}..., 状态: {existing_task['status']})")
        
        task_id = str(uuid.uuid4())
        
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute('''
                INSERT INTO tasks (task_id, task_type, status, params)
                VALUES (?, ?, ?, ?)
            ''', (
                task_id,
                task_type.value,
                TaskStatus.PENDING.value,
                json.dumps(params, ensure_ascii=False)
            ))
            conn.commit()
        
        logger.info(f"创建任务: {task_id} ({task_type.value})")
        return task_id
    
    def get_task_status(self, task_id: str) -> Optional[Dict]:
        """获取任务状态"""
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute('''
                SELECT task_id, task_type, status, params, result, error_message,
                       created_at, started_at, completed_at, progress, total_items, current_item
                FROM tasks WHERE task_id = ?
            ''', (task_id,))
            
            row = cursor.fetchone()
            if not row:
                return None
            
            return {
                'task_id': row[0],
                'task_type': row[1],
                'status': row[2],
                'params': json.loads(row[3]) if row[3] else {},
                'result': json.loads(row[4]) if row[4] else None,
                'error_message': row[5],
                'created_at': row[6],
                'started_at': row[7],
                'completed_at': row[8],
                'progress': row[9],
                'total_items': row[10],
                'current_item': row[11]
            }
    
    def update_task_status(self, task_id: str, status: TaskStatus, 
                          result: Dict = None, error_message: str = None,
                          progress: int = None, total_items: int = None, 
                          current_item: str = None):
        """更新任务状态"""
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            
            update_fields = ['status = ?']
            params = [status.value]
            
            if status == TaskStatus.RUNNING:
                update_fields.append('started_at = ?')
                params.append(datetime.now())
            elif status in [TaskStatus.COMPLETED, TaskStatus.FAILED, TaskStatus.CANCELLED]:
                update_fields.append('completed_at = ?')
                params.append(datetime.now())
            
            if result is not None:
                update_fields.append('result = ?')
                params.append(json.dumps(result, ensure_ascii=False))
            
            if error_message is not None:
                update_fields.append('error_message = ?')
                params.append(error_message)
            
            if progress is not None:
                update_fields.append('progress = ?')
                params.append(progress)
            
            if total_items is not None:
                update_fields.append('total_items = ?')
                params.append(total_items)
            
            if current_item is not None:
                update_fields.append('current_item = ?')
                params.append(current_item)
            
            params.append(task_id)
            
            cursor.execute(f'''
                UPDATE tasks SET {', '.join(update_fields)} WHERE task_id = ?
            ''', params)
            conn.commit()
    
    def get_all_tasks(self, status: TaskStatus = None, limit: int = 50) -> List[Dict]:
        """获取所有任务"""
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            
            if status:
                cursor.execute('''
                    SELECT task_id, task_type, status, created_at, started_at, completed_at, progress, total_items
                    FROM tasks WHERE status = ? ORDER BY created_at DESC LIMIT ?
                ''', (status.value, limit))
            else:
                cursor.execute('''
                    SELECT task_id, task_type, status, created_at, started_at, completed_at, progress, total_items
                    FROM tasks ORDER BY created_at DESC LIMIT ?
                ''', (limit,))
            
            rows = cursor.fetchall()
            return [{
                'task_id': row[0],
                'task_type': row[1],
                'status': row[2],
                'created_at': row[3],
                'started_at': row[4],
                'completed_at': row[5],
                'progress': row[6],
                'total_items': row[7]
            } for row in rows]
    
    async def execute_batch_process_task(self, task_id: str, params: Dict):
        """执行批量处理任务"""
        try:
            # 更新任务状态为运行中
            self.update_task_status(task_id, TaskStatus.RUNNING)
            
            # 导入处理器
            from youtube_channel_processor import get_processor
            processor = get_processor()
            
            # 包装原始方法以支持进度回调
            original_method = processor.process_channel_batch
            
            async def progress_callback(current: int, total: int, current_item: str):
                """进度回调"""
                progress = int((current / total) * 100) if total > 0 else 0
                self.update_task_status(
                    task_id, 
                    TaskStatus.RUNNING,
                    progress=progress,
                    total_items=total,
                    current_item=current_item
                )
            
            # 执行批量处理（需要修改原方法以支持回调）
            result = await self._execute_with_progress(
                processor, params, progress_callback
            )
            
            # 更新任务为完成状态
            self.update_task_status(task_id, TaskStatus.COMPLETED, result=result)
            logger.info(f"任务完成: {task_id}")
            
        except Exception as e:
            error_msg = str(e)
            self.update_task_status(task_id, TaskStatus.FAILED, error_message=error_msg)
            logger.error(f"任务失败: {task_id}, 错误: {error_msg}")
        finally:
            # 从运行任务中移除
            if task_id in self.running_tasks:
                del self.running_tasks[task_id]
    
    async def _execute_with_progress(self, processor, params, progress_callback):
        """执行带进度回调的批量处理"""
        # 获取频道视频列表
        await progress_callback(0, 100, "正在获取频道视频列表...")
        channel_info, videos = processor.get_channel_videos(
            params['channel_url'], 
            params.get('max_videos', 50)
        )
        
        # 保存频道和视频信息
        processor.save_channel_and_videos(channel_info, videos)
        
        # 处理视频字幕
        success_count = 0
        failed_count = 0
        total_videos = len(videos)
        
        for i, video in enumerate(videos, 1):
            current_item = f"正在处理: {video['title'][:30]}..."
            await progress_callback(i, total_videos, current_item)
            
            # 检查是否已经处理过
            with sqlite3.connect(processor.db_path) as conn:
                cursor = conn.cursor()
                cursor.execute('SELECT subtitle_extracted FROM videos WHERE video_id = ?', 
                             (video['video_id'],))
                result = cursor.fetchone()
                
                if result and result[0]:
                    success_count += 1
                    continue
            
            # 提取字幕
            subtitles_data = processor.extract_video_subtitles(
                video['video_id'], 
                video['url'], 
                params.get('subtitle_lang', 'en')
            )
            
            if subtitles_data:
                processor.save_subtitles(subtitles_data, video['video_id'])
                success_count += 1
            else:
                failed_count += 1
            
            # 延迟避免频率限制
            await asyncio.sleep(2)
        
        return {
            'status': 'completed',
            'channel_info': channel_info,
            'total_videos': total_videos,
            'success_count': success_count,
            'failed_count': failed_count,
            'processed_at': datetime.now().isoformat()
        }
    
    async def start_task(self, task_id: str):
        """启动任务"""
        task_info = self.get_task_status(task_id)
        if not task_info:
            raise ValueError(f"任务不存在: {task_id}")
        
        if task_info['status'] != TaskStatus.PENDING.value:
            raise ValueError(f"任务状态错误: {task_info['status']}")
        
        # 检查当前运行的任务数量，限制并发
        if len(self.running_tasks) >= 1:  # 限制同时只能运行1个任务
            raise ValueError("已有任务在运行中，请等待当前任务完成后再启动新任务")
        
        # 创建异步任务
        if task_info['task_type'] == TaskType.BATCH_PROCESS.value:
            # 使用线程池执行阻塞操作
            task = asyncio.create_task(
                self._execute_task_in_thread(task_id, task_info['params'])
            )
            self.running_tasks[task_id] = task
            logger.info(f"启动任务: {task_id}")
        else:
            raise ValueError(f"未知任务类型: {task_info['task_type']}")
    
    def cancel_task(self, task_id: str) -> bool:
        """取消任务"""
        if task_id in self.running_tasks:
            task = self.running_tasks[task_id]
            task.cancel()
            del self.running_tasks[task_id]
            self.update_task_status(task_id, TaskStatus.CANCELLED)
            logger.info(f"取消任务: {task_id}")
            return True
        
        # 如果任务还未开始，直接标记为取消
        task_info = self.get_task_status(task_id)
        if task_info and task_info['status'] == TaskStatus.PENDING.value:
            self.update_task_status(task_id, TaskStatus.CANCELLED)
            return True
        
        return False
    
    async def _execute_task_in_thread(self, task_id: str, params: Dict):
        """在线程池中执行阻塞任务，避免阻塞事件循环"""
        loop = asyncio.get_event_loop()
        
        # 使用线程池执行器
        with concurrent.futures.ThreadPoolExecutor(max_workers=1) as executor:
            try:
                # 在线程中执行阻塞操作
                result = await loop.run_in_executor(
                    executor,
                    self._sync_execute_batch_process,
                    task_id,
                    params
                )
                return result
            except Exception as e:
                logger.error(f"线程池执行任务失败: {task_id}, 错误: {str(e)}")
                raise
    
    def _sync_execute_batch_process(self, task_id: str, params: Dict):
        """同步执行批量处理（在线程中运行）"""
        try:
            # 更新任务状态为运行中
            self.update_task_status(task_id, TaskStatus.RUNNING)
            
            # 导入处理器
            from youtube_channel_processor import get_processor
            processor = get_processor()
            
            # 添加Cookie文件参数
            cookie_file = params.get('cookie_file', 'test_cookies.txt')
            
            # 获取频道视频列表
            self.update_task_status(
                task_id, TaskStatus.RUNNING, 
                progress=10, total_items=100, 
                current_item="正在获取频道视频列表..."
            )
            
            # 模拟批量处理逻辑
            import time
            channel_url = params['channel_url']
            max_videos = params.get('max_videos', 50)
            subtitle_lang = params.get('subtitle_lang', 'en')
            
            # 更新进度
            self.update_task_status(
                task_id, TaskStatus.RUNNING,
                progress=50, total_items=100,
                current_item=f"正在处理频道: {channel_url}"
            )
            
            # 模拟处理时间
            time.sleep(5)
            
            # 完成任务
            result = {
                'status': 'completed',
                'channel_url': channel_url,
                'total_videos': max_videos,
                'success_count': 0,  # 实际处理后更新
                'failed_count': 0,
                'processed_at': datetime.now().isoformat(),
                'message': '批量处理完成（演示版本）'
            }
            
            self.update_task_status(task_id, TaskStatus.COMPLETED, result=result)
            logger.info(f"任务完成: {task_id}")
            return result
            
        except Exception as e:
            error_msg = str(e)
            self.update_task_status(task_id, TaskStatus.FAILED, error_message=error_msg)
            logger.error(f"任务失败: {task_id}, 错误: {error_msg}")
            raise
        finally:
            # 从运行任务中移除
            if task_id in self.running_tasks:
                del self.running_tasks[task_id]
    
    def _normalize_channel_url(self, channel_url: str) -> str:
        """标准化频道URL，用于重复检测"""
        import re
        from urllib.parse import urlparse, parse_qs
        
        if not channel_url:
            return ""
        
        # 移除末尾的斜杠和空格
        url = channel_url.strip().rstrip('/')
        
        # 标准化不同的YouTube频道URL格式
        # @username -> /c/username 或 /channel/xxx
        # /c/name -> 标准格式
        # /channel/id -> 标准格式
        # /user/name -> 标准格式
        
        # 提取关键的频道标识符
        patterns = [
            r'youtube\.com/@([^/?]+)',           # @username
            r'youtube\.com/c/([^/?]+)',          # /c/name  
            r'youtube\.com/channel/([^/?]+)',    # /channel/id
            r'youtube\.com/user/([^/?]+)',       # /user/name
        ]
        
        for pattern in patterns:
            match = re.search(pattern, url.lower())
            if match:
                identifier = match.group(1)
                # 返回标准化格式
                if url.lower().find('/@') != -1:
                    return f"https://www.youtube.com/@{identifier}"
                elif url.lower().find('/c/') != -1:
                    return f"https://www.youtube.com/c/{identifier}"
                elif url.lower().find('/channel/') != -1:
                    return f"https://www.youtube.com/channel/{identifier}"
                elif url.lower().find('/user/') != -1:
                    return f"https://www.youtube.com/user/{identifier}"
        
        # 如果没有匹配到已知格式，返回清理后的原URL
        return url.lower()
    
    def _check_duplicate_channel_task(self, channel_url: str) -> Optional[Dict]:
        """
        检查是否已有相同频道的任务在处理中
        
        Args:
            channel_url: 频道URL
            
        Returns:
            如果找到重复任务，返回任务信息；否则返回None
        """
        if not channel_url:
            return None
            
        normalized_url = self._normalize_channel_url(channel_url)
        
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            
            # 查找所有未完成的批量处理任务
            cursor.execute('''
                SELECT task_id, task_type, status, params, created_at
                FROM tasks 
                WHERE task_type = ? 
                AND status IN (?, ?, ?)
                ORDER BY created_at DESC
            ''', (
                TaskType.BATCH_PROCESS.value,
                TaskStatus.PENDING.value,
                TaskStatus.RUNNING.value,
                TaskStatus.RUNNING.value  # 检查两次运行状态以确保
            ))
            
            rows = cursor.fetchall()
            
            for row in rows:
                task_id, task_type, status, params_json, created_at = row
                try:
                    params = json.loads(params_json)
                    task_channel_url = params.get('channel_url', '')
                    normalized_task_url = self._normalize_channel_url(task_channel_url)
                    
                    # 比较标准化后的URL
                    if normalized_url == normalized_task_url:
                        return {
                            'task_id': task_id,
                            'status': status,
                            'channel_url': task_channel_url,
                            'created_at': created_at
                        }
                except json.JSONDecodeError:
                    continue
        
        return None
    
    def get_channel_task_history(self, channel_url: str, limit: int = 10) -> List[Dict]:
        """获取指定频道的任务历史"""
        normalized_url = self._normalize_channel_url(channel_url)
        
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            
            cursor.execute('''
                SELECT task_id, status, created_at, completed_at, result
                FROM tasks 
                WHERE task_type = ?
                ORDER BY created_at DESC
                LIMIT ?
            ''', (TaskType.BATCH_PROCESS.value, limit * 2))  # 获取更多以便过滤
            
            rows = cursor.fetchall()
            
            matching_tasks = []
            for row in rows:
                task_id, status, created_at, completed_at, result_json = row
                
                # 获取任务参数
                task_info = self.get_task_status(task_id)
                if task_info:
                    task_channel_url = task_info['params'].get('channel_url', '')
                    if self._normalize_channel_url(task_channel_url) == normalized_url:
                        result = json.loads(result_json) if result_json else None
                        matching_tasks.append({
                            'task_id': task_id,
                            'status': status,
                            'created_at': created_at,
                            'completed_at': completed_at,
                            'result': result
                        })
                        
                        if len(matching_tasks) >= limit:
                            break
            
            return matching_tasks

# 全局任务管理器实例
_task_manager_instance = None

def get_task_manager():
    """获取任务管理器实例（单例模式）"""
    global _task_manager_instance
    if _task_manager_instance is None:
        _task_manager_instance = TaskManager()
    return _task_manager_instance