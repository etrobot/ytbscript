import asyncio
import logging
import time
from datetime import datetime, timezone, timedelta
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from d1_task_manager import get_task_manager
from execute_d1_task import execute_task

# Setup logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

class TaskScheduler:
    def __init__(self):
        self.task_manager = get_task_manager()
        self.scheduler = AsyncIOScheduler()

    async def run_task(self, task_raw, original_scheduled_time=None):
        """调用 execute_d1_task 运行任务"""
        task_id = task_raw.get('id')
        logger.info(f"--- 调度器触发任务执行: {task_id} ---")
        
        # 1. 计算目标计划时间戳
        # 如果没有传入明确的计划时间，尝试从任务信息中获取
        if not original_scheduled_time:
            sh = task_raw.get('scheduled_hour') or task_raw.get('scheduledHour')
            sm = task_raw.get('scheduled_minute') if task_raw.get('scheduled_minute') is not None else task_raw.get('scheduledMinute', 0)
            if sh is not None:
                original_scheduled_time = (sh, sm)

        scheduled_timestamp = None
        if original_scheduled_time:
            sh, sm = original_scheduled_time
            now_utc = datetime.now(timezone.utc)
            # 以当前日期构建计划时间
            dt = now_utc.replace(hour=sh, minute=sm, second=0, microsecond=0)
            
            # 处理跨天：如果提前运行（比如 23:30 跑 00:30 的任务），需要日期 +1
            if dt < now_utc - timedelta(hours=2):
                dt += timedelta(days=1)
                
            scheduled_timestamp = int(dt.timestamp() * 1000)
            logger.info(f"目标计划时间: {dt.strftime('%Y-%m-%d %H:%M:%S UTC')}")

        # 2. 直接调用测试成功的核心逻辑
        try:
            await execute_task(task_id, scheduled_timestamp=scheduled_timestamp)
            logger.info(f"--- 任务 {task_id} 执行完成 ---")
        except Exception as e:
            logger.error(f"执行任务 {task_id} 时发生未捕获错误: {e}")

    async def check_schedule(self):
        """每分钟检查一次是否有任务需要运行"""
        now_utc = datetime.now(timezone.utc)
        current_hour_utc = now_utc.hour
        current_minute_utc = now_utc.minute
        
        # 提前 1 小时运行策略
        target_hour = (current_hour_utc + 1) % 24
        target_minute = current_minute_utc
        
        try:
            tasks = self.task_manager.get_active_tasks()
            for task in tasks:
                sh = task.get('scheduled_hour') or task.get('scheduledHour')
                sm = task.get('scheduled_minute') if task.get('scheduled_minute') is not None else task.get('scheduledMinute', 0)
                last_exec = task.get('last_executed_at') or task.get('lastExecutedAt')
                
                if sh == target_hour and sm == target_minute:
                    # 避免一分钟内重复触发
                    should_run = True
                    if last_exec:
                        # 检查是否在 60 秒内运行过
                        if (int(time.time() * 1000) - last_exec) < 60000:
                            should_run = False
                    
                    if should_run:
                        logger.info(f"触达计划时间 (早一小时执行): 任务 {task['id']} (设定 {sh:02d}:{sm:02d} UTC)")
                        # 异步启动任务，不阻塞调度循环
                        asyncio.create_task(self.run_task(task, original_scheduled_time=(sh, sm)))
        except Exception as e:
            logger.error(f"检查调度异常: {e}")

    def start(self):
        # 启动定时作业
        self.scheduler.add_job(self.check_schedule, 'interval', minutes=1, next_run_time=datetime.now())
        self.scheduler.start()
        logger.info("Scheduler 已启动（每分钟检查，提前1小时运行策略）")
        
        try:
            asyncio.get_event_loop().run_forever()
        except (KeyboardInterrupt, SystemExit):
            pass

def get_scheduler():
    return TaskScheduler()

if __name__ == "__main__":
    from dotenv import load_dotenv
    load_dotenv()
    
    scheduler = get_scheduler()
    scheduler.start()
