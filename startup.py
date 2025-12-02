#!/usr/bin/env python3
"""
项目启动脚本 - 统一的启动入口
"""

import uvicorn
from pathlib import Path

def start_server():
    """启动FastAPI服务器"""
    print("🚀 启动YouTube字幕批量处理服务...")
    print("📁 数据库文件: youtube_channels.db")
    print("🍪 Cookie目录: ./cookies/")
    print("📖 API文档: http://localhost:24314/docs")
    print("-" * 50)
    
    # 确保必要的目录存在
    BASE_DIR = Path(__file__).parent.absolute()
    COOKIE_DIR = BASE_DIR / "cookies"
    COOKIE_DIR.mkdir(exist_ok=True)
    
    # 启动服务器
    uvicorn.run(
        "main:app", 
        host="0.0.0.0", 
        port=24314, 
        reload=True,
        log_level="info"
    )

if __name__ == "__main__":
    start_server()