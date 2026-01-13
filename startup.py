#!/usr/bin/env python3
"""
项目启动脚本 - 统一的启动入口和服务初始化
"""

import asyncio
import os
import logging
import threading
from datetime import datetime
from pathlib import Path
from contextlib import asynccontextmanager
from dotenv import load_dotenv
import uvicorn

# 配置日志
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# 加载环境变量
load_dotenv()

def setup_directories():
    """设置必要的目录结构"""
    BASE_DIR = Path(__file__).parent.absolute()
    COOKIE_DIR = Path(os.getenv("COOKIES_DIR", str(BASE_DIR / "cookies")))
    DOWNLOADS_DIR = Path(os.getenv("DOWNLOADS_DIR", str(BASE_DIR / "downloads")))
    
    COOKIE_DIR.mkdir(parents=True, exist_ok=True)
    DOWNLOADS_DIR.mkdir(parents=True, exist_ok=True)
    
    logger.info(f"✅ 目录结构已确认: BASE_DIR={BASE_DIR}")
    logger.info(f"✅ Cookie目录: {COOKIE_DIR}")
    logger.info(f"✅ 下载目录: {DOWNLOADS_DIR}")
    return BASE_DIR, COOKIE_DIR, DOWNLOADS_DIR

async def initialize_database():
    """初始化数据库"""
    try:
        from youtube_channel_processor import get_processor
        processor = get_processor()
        logger.info("✅ YouTube频道处理器已初始化")
        logger.info("✅ 数据库表已创建")
        return processor
    except Exception as e:
        logger.error(f"❌ 数据库初始化失败: {e}")
        raise

async def initialize_task_manager():
    """初始化任务管理器"""
    try:
        from task_manager import get_task_manager
        task_manager = get_task_manager()
        logger.info("✅ 任务管理器已初始化")
        logger.info("✅ 任务队列系统已就绪")
        return task_manager
    except Exception as e:
        logger.error(f"❌ 任务管理器初始化失败: {e}")
        raise

async def initialize_scheduler():
    """初始化调度服务"""
    try:
        from scheduler_service import TaskScheduler
        
        scheduler = TaskScheduler()
        
        # 在当前事件循环中启动调度器
        # 修正：使用 minutes=1 而不是 hours=1，确保每分钟检查一次
        scheduler.scheduler.add_job(
            scheduler.check_schedule, 
            'interval', 
            minutes=1,  # 每分钟检查一次
            next_run_time=datetime.now()
        )
        scheduler.scheduler.start()
        
        logger.info("✅ 调度服务已启动（每分钟检查，提前1小时运行策略）")
        logger.info("✅ AI总结定时任务已就绪")
        return scheduler
    except Exception as e:
        logger.error(f"⚠️ 调度服务启动失败: {e}")
        return None

def create_app_lifespan():
    """创建FastAPI应用的生命周期管理器"""
    @asynccontextmanager
    async def app_lifespan(app):
        """统一的生命周期管理"""
        logger.info("🚀 开始初始化应用服务...")
        
        # 设置目录
        setup_directories()
        
        # 初始化各个组件
        processor = await initialize_database()
        task_manager = await initialize_task_manager()
        scheduler = await initialize_scheduler()
        
        # 保存到app状态
        app.state.processor = processor
        app.state.task_manager = task_manager
        app.state.scheduler = scheduler
        app.state.scheduler_thread = None  # 不需要单独线程
        
        logger.info("✅ 所有服务初始化完成")
        
        yield
        
        # 清理资源
        logger.info("🔄 开始清理应用资源...")
        if scheduler and scheduler.scheduler:
            try:
                scheduler.scheduler.shutdown(wait=False)
                logger.info("✅ 调度服务已停止")
            except Exception as e:
                logger.error(f"⚠️ 调度服务停止时出错: {e}")
        
        logger.info("✅ 应用资源清理完成")
    
    return app_lifespan

def get_app_config():
    """获取应用配置"""
    config = {
        "title": "YouTube Subtitle Service",
        "description": "YouTube 字幕下载和批量处理服务 - 增强版",
        "version": "2.2.0",
        "host": os.getenv("HOST", "0.0.0.0"),
        "port": int(os.getenv("PORT", 24314)),
        "reload": os.getenv("DEBUG", "false").lower() == "true",
        "log_level": os.getenv("LOG_LEVEL", "info")
    }
    return config

def print_startup_banner():
    """打印启动横幅"""
    config = get_app_config()
    print("=" * 60)
    print("🚀 YouTube 字幕批量处理服务")
    print("=" * 60)
    print(f"📖 服务版本: {config['version']}")
    print(f"🌐 服务地址: http://{config['host']}:{config['port']}")
    print(f"📚 API文档: http://{config['host']}:{config['port']}/docs")
    print(f"📁 数据库文件: {os.getenv('DB_PATH', 'youtube_channels.db')}")
    print(f"🍪 Cookie目录: {os.getenv('COOKIES_DIR', './cookies/')}")
    print(f"📦 下载目录: {os.getenv('DOWNLOADS_DIR', './downloads/')}")
    print("=" * 60)
    print("🔧 集成服务:")
    print("  • FastAPI Web服务")
    print("  • YouTube频道处理器")
    print("  • 任务队列管理器")
    print("  • AI总结调度服务")
    print("  • Cloudflare D1数据库")
    print("  • OpenAI API集成")
    print("=" * 60)

def start_server():
    """启动FastAPI服务器"""
    print_startup_banner()
    
    config = get_app_config()
    
    # 启动服务器
    uvicorn.run(
        "main:app",
        host=config["host"],
        port=config["port"],
        reload=config["reload"],
        log_level=config["log_level"]
    )

if __name__ == "__main__":
    start_server()