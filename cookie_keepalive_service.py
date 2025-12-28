"""
Cookie保活服务 - 智能管理YouTube Cookie
功能：
1. 定期轻量级访问YouTube保持cookie活跃
2. 任务运行时自动暂停保活
3. Cookie有效性检测
4. Cookie元数据管理
"""

import asyncio
import logging
import time
import json
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional, Dict
import yt_dlp
from threading import Lock

logger = logging.getLogger(__name__)


class CookieKeepAliveService:
    """Cookie保活服务"""
    
    def __init__(self, cookie_dir: Path, check_interval: int = 300):
        """
        初始化保活服务
        
        Args:
            cookie_dir: Cookie目录路径
            check_interval: 保活检查间隔（秒），默认5分钟
        """
        self.cookie_dir = cookie_dir
        self.check_interval = check_interval
        self.metadata_file = cookie_dir / "cookie_metadata.json"
        self.running = False
        self.paused = False
        self.task = None
        self.lock = Lock()
        
        # 保活用的测试URL（轻量级）
        self.keepalive_urls = [
            "https://www.youtube.com/",  # 主页
            "https://www.youtube.com/feed/subscriptions",  # 订阅页
        ]
        
        self._load_metadata()
    
    def _load_metadata(self):
        """加载cookie元数据"""
        if self.metadata_file.exists():
            try:
                with open(self.metadata_file, 'r', encoding='utf-8') as f:
                    self.metadata = json.load(f)
                logger.info(f"加载cookie元数据: {len(self.metadata)} 个cookie文件")
            except Exception as e:
                logger.error(f"加载元数据失败: {e}")
                self.metadata = {}
        else:
            self.metadata = {}
    
    def _save_metadata(self):
        """保存cookie元数据"""
        try:
            with open(self.metadata_file, 'w', encoding='utf-8') as f:
                json.dump(self.metadata, f, indent=2, ensure_ascii=False)
            logger.debug("保存cookie元数据成功")
        except Exception as e:
            logger.error(f"保存元数据失败: {e}")
    
    def register_cookie(self, cookie_name: str, cookie_path: Path):
        """
        注册新的cookie文件
        
        Args:
            cookie_name: Cookie名称
            cookie_path: Cookie文件路径
        """
        with self.lock:
            self.metadata[cookie_name] = {
                'path': str(cookie_path),
                'registered_at': datetime.now().isoformat(),
                'last_validated': None,
                'last_keepalive': None,
                'validation_count': 0,
                'keepalive_count': 0,
                'is_valid': None,
                'last_error': None
            }
            self._save_metadata()
            logger.info(f"注册cookie: {cookie_name}")
    
    def get_active_cookie(self) -> Optional[tuple]:
        """
        获取当前活跃的cookie
        
        Returns:
            (cookie_name, cookie_path) 或 None
        """
        # 优先使用 cookies.txt
        default_cookie = self.cookie_dir / "cookies.txt"
        if default_cookie.exists():
            cookie_name = "cookies.txt"
            if cookie_name not in self.metadata:
                self.register_cookie(cookie_name, default_cookie)
            return (cookie_name, default_cookie)
        
        # 否则使用第一个找到的cookie文件
        for cookie_file in self.cookie_dir.glob("*.txt"):
            cookie_name = cookie_file.name
            if cookie_name not in self.metadata:
                self.register_cookie(cookie_name, cookie_file)
            return (cookie_name, cookie_file)
        
        return None
    
    async def validate_cookie(self, cookie_path: Path) -> bool:
        """
        验证cookie是否有效
        
        Args:
            cookie_path: Cookie文件路径
            
        Returns:
            True if valid, False otherwise
        """
        try:
            # 使用yt-dlp尝试获取YouTube主页信息
            ydl_opts = {
                'quiet': True,
                'no_warnings': True,
                'extract_flat': True,
                'cookiefile': str(cookie_path),
                'socket_timeout': 30,
            }
            
            test_url = "https://www.youtube.com/"
            
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                # 尝试提取信息，如果cookie无效会抛出异常
                info = ydl.extract_info(test_url, download=False)
                
                if info:
                    logger.info(f"Cookie验证成功: {cookie_path.name}")
                    return True
                else:
                    logger.warning(f"Cookie验证失败: 无法获取信息")
                    return False
                    
        except Exception as e:
            error_msg = str(e)
            logger.error(f"Cookie验证失败: {error_msg}")
            
            # 检查是否是登录相关错误
            if any(keyword in error_msg.lower() for keyword in ['login', 'sign in', 'authentication', 'unauthorized']):
                logger.error("Cookie可能已过期，需要重新获取")
                return False
            
            # 其他错误也视为验证失败
            return False
    
    async def perform_keepalive(self, cookie_path: Path) -> bool:
        """
        执行保活操作
        
        Args:
            cookie_path: Cookie文件路径
            
        Returns:
            True if successful, False otherwise
        """
        try:
            # 使用轻量级请求保活
            ydl_opts = {
                'quiet': True,
                'no_warnings': True,
                'extract_flat': True,  # 只获取基本信息，不深入提取
                'cookiefile': str(cookie_path),
                'socket_timeout': 30,
                'playlist_items': '1',  # 只处理第一个项目
            }
            
            # 轮流使用不同URL避免被检测
            url = self.keepalive_urls[int(time.time()) % len(self.keepalive_urls)]
            
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                try:
                    info = ydl.extract_info(url, download=False)
                except Exception as e:
                    error_msg = str(e)
                    if "[youtube:tab] trending" in error_msg and "redirected" in error_msg.lower():
                        info = ydl.extract_info("https://www.youtube.com/", download=False)
                    else:
                        raise
                
                if info:
                    logger.info(f"Cookie保活成功: {cookie_path.name}")
                    return True
                else:
                    logger.warning(f"Cookie保活失败: 无法访问YouTube")
                    return False
                    
        except Exception as e:
            logger.error(f"保活操作失败: {str(e)}")
            return False
    
    def pause(self):
        """暂停保活（有任务运行时调用）"""
        with self.lock:
            self.paused = True
            logger.info("⏸️  Cookie保活已暂停（任务运行中）")
    
    def resume(self):
        """恢复保活（任务完成后调用）"""
        with self.lock:
            self.paused = False
            logger.info("▶️  Cookie保活已恢复")
    
    def is_paused(self) -> bool:
        """检查是否暂停"""
        with self.lock:
            return self.paused
    
    async def _keepalive_loop(self):
        """保活循环"""
        logger.info(f"🚀 Cookie保活服务启动 (检查间隔: {self.check_interval}秒)")
        
        while self.running:
            try:
                # 检查是否暂停
                if self.is_paused():
                    logger.debug("保活循环暂停中，等待恢复...")
                    await asyncio.sleep(10)  # 暂停时每10秒检查一次
                    continue
                
                # 获取活跃cookie
                cookie_info = self.get_active_cookie()
                
                if not cookie_info:
                    logger.warning("未找到可用的cookie文件，等待...")
                    await asyncio.sleep(60)
                    continue
                
                cookie_name, cookie_path = cookie_info
                
                # 执行保活操作
                logger.info(f"🔄 执行cookie保活: {cookie_name}")
                success = await self.perform_keepalive(cookie_path)
                
                # 更新元数据
                with self.lock:
                    if cookie_name in self.metadata:
                        self.metadata[cookie_name]['last_keepalive'] = datetime.now().isoformat()
                        self.metadata[cookie_name]['keepalive_count'] += 1
                        
                        if success:
                            self.metadata[cookie_name]['is_valid'] = True
                            self.metadata[cookie_name]['last_error'] = None
                        else:
                            self.metadata[cookie_name]['last_error'] = 'keepalive_failed'
                        
                        self._save_metadata()
                
                # 如果保活失败，尝试验证cookie
                if not success:
                    logger.warning(f"保活失败，验证cookie有效性...")
                    is_valid = await self.validate_cookie(cookie_path)
                    
                    with self.lock:
                        if cookie_name in self.metadata:
                            self.metadata[cookie_name]['is_valid'] = is_valid
                            self.metadata[cookie_name]['last_validated'] = datetime.now().isoformat()
                            self.metadata[cookie_name]['validation_count'] += 1
                            
                            if not is_valid:
                                self.metadata[cookie_name]['last_error'] = 'validation_failed'
                                logger.error(f"❌ Cookie已失效: {cookie_name}，请重新获取并保存")
                            
                            self._save_metadata()
                
                # 等待下一次检查
                logger.info(f"⏳ 下次保活时间: {self.check_interval}秒后")
                await asyncio.sleep(self.check_interval)
                
            except Exception as e:
                logger.error(f"保活循环出错: {e}", exc_info=True)
                await asyncio.sleep(60)  # 出错后等待1分钟再试
    
    def start(self):
        """启动保活服务"""
        if self.running:
            logger.warning("保活服务已在运行")
            return
        
        self.running = True
        self.task = asyncio.create_task(self._keepalive_loop())
        logger.info("✅ Cookie保活服务已启动")
    
    async def stop(self):
        """停止保活服务"""
        if not self.running:
            return
        
        logger.info("正在停止Cookie保活服务...")
        self.running = False
        
        if self.task:
            self.task.cancel()
            try:
                await self.task
            except asyncio.CancelledError:
                pass
        
        logger.info("✅ Cookie保活服务已停止")
    
    def get_status(self) -> Dict:
        """获取服务状态"""
        with self.lock:
            cookie_info = self.get_active_cookie()
            
            status = {
                'running': self.running,
                'paused': self.paused,
                'check_interval': self.check_interval,
                'active_cookie': cookie_info[0] if cookie_info else None,
                'cookies': {}
            }
            
            for cookie_name, meta in self.metadata.items():
                status['cookies'][cookie_name] = {
                    'registered_at': meta.get('registered_at'),
                    'last_keepalive': meta.get('last_keepalive'),
                    'last_validated': meta.get('last_validated'),
                    'keepalive_count': meta.get('keepalive_count', 0),
                    'validation_count': meta.get('validation_count', 0),
                    'is_valid': meta.get('is_valid'),
                    'last_error': meta.get('last_error')
                }
            
            return status


# 全局实例
_keepalive_service = None

def get_keepalive_service(cookie_dir: Path = None, check_interval: int = 300) -> CookieKeepAliveService:
    """获取保活服务实例（单例模式）"""
    global _keepalive_service
    
    if _keepalive_service is None:
        if cookie_dir is None:
            raise ValueError("首次调用需要提供cookie_dir参数")
        _keepalive_service = CookieKeepAliveService(cookie_dir, check_interval)
    
    return _keepalive_service
