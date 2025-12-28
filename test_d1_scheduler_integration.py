"""
完整的D1定时任务测试流程:
1. 在D1中创建定时任务
2. 读取D1定时任务
3. 通过main.py的API获取频道字幕（更新本地数据库）
4. 生成AI总结
5. 回写D1的ai_headlines表
"""

import asyncio
import os
import time
import json
import aiohttp
from datetime import datetime
from dotenv import load_dotenv
from d1_client import D1Client
from scheduler_service import TaskScheduler

load_dotenv()

# API配置
API_BASE_URL = os.getenv("API_BASE_URL", "http://localhost:24314")
API_TOKEN = os.getenv("API_TOKEN", "Abcd123456")

async def test_d1_scheduler_integration():
    """完整的D1定时任务集成测试"""
    
    print("=" * 80)
    print("D1定时任务集成测试")
    print("=" * 80)
    
    # 初始化客户端
    d1 = D1Client()
    scheduler = TaskScheduler()
    
    # 确保表已初始化
    await scheduler.init_db()
    
    # 测试频道ID (这里使用一个真实的YouTube频道ID进行测试)
    # 你可以替换成任何你想测试的频道
    test_channel_id = os.getenv("TEST_CHANNEL_ID", "UCBJycsmduvYEL83R_U4JriQ")  # MKBHD
    test_user_id = "test_user_001"
    test_task_id = f"task_test_{int(time.time())}"
    
    print(f"\n📋 测试配置:")
    print(f"  - 频道ID: {test_channel_id}")
    print(f"  - 用户ID: {test_user_id}")
    print(f"  - 任务ID: {test_task_id}")
    
    try:
        # ========== 步骤1: 在D1中创建定时任务 ==========
        print("\n" + "=" * 80)
        print("步骤1: 在D1中创建定时任务")
        print("=" * 80)
        
        now = datetime.now()
        current_hour = now.hour
        current_minute = now.minute
        task_data = {
            'id': test_task_id,
            'user_id': test_user_id,
            'task_type': 'daily_summary',
            'scheduled_hour': current_hour,  # 设置为当前小时，方便测试
            'scheduled_minute': current_minute,  # 设置为当前分钟，方便测试
            'feed_ids': test_channel_id,
            'custom_source_ids': None,
            'prompt': '请总结这些视频的主要内容，生成一个新闻标题和摘要。',
            'is_active': 1,
            'last_executed_at': None,
            'created_at': int(time.time()),
            'updated_at': int(time.time())
        }
        
        d1.execute("""
            INSERT INTO scheduled_tasks 
            (id, user_id, task_type, scheduled_hour, scheduled_minute, feed_ids, custom_source_ids, 
             prompt, is_active, last_executed_at, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, [
            task_data['id'],
            task_data['user_id'],
            task_data['task_type'],
            task_data['scheduled_hour'],
            task_data['scheduled_minute'],
            task_data['feed_ids'],
            task_data['custom_source_ids'],
            task_data['prompt'],
            task_data['is_active'],
            task_data['last_executed_at'],
            task_data['created_at'],
            task_data['updated_at']
        ])
        
        print(f"✅ 成功创建定时任务: {test_task_id}")
        print(f"   调度时间: 每天 {current_hour:02d}:{current_minute:02d}")
        
        # ========== 步骤2: 从D1读取定时任务 ==========
        print("\n" + "=" * 80)
        print("步骤2: 从D1读取定时任务")
        print("=" * 80)
        
        tasks = d1.fetch_all(
            "SELECT * FROM scheduled_tasks WHERE id = ? AND is_active = 1",
            [test_task_id]
        )
        
        if not tasks:
            raise Exception("未能从D1读取到任务")
        
        task = tasks[0]
        print(f"✅ 成功读取任务:")
        print(f"   任务ID: {task['id']}")
        print(f"   用户ID: {task['user_id']}")
        print(f"   频道IDs: {task['feed_ids']}")
        print(f"   提示词: {task['prompt']}")
        
        # ========== 步骤3: 通过API获取频道字幕 ==========
        print("\n" + "=" * 80)
        print("步骤3: 通过main.py的API获取频道字幕")
        print("=" * 80)
        
        channel_url = f"https://www.youtube.com/channel/{test_channel_id}"
        
        async with aiohttp.ClientSession() as session:
            # 调用批量处理API
            api_url = f"{API_BASE_URL}/channel/batch-process-sync"
            headers = {
                "X-API-Token": API_TOKEN,
                "Content-Type": "application/json"
            }
            payload = {
                "channel_url": channel_url,
                "max_videos": 3,  # 只获取最新3个视频进行测试
                "subtitle_lang": "en"
            }
            
            print(f"📡 调用API: {api_url}")
            print(f"   参数: {payload}")
            
            async with session.post(api_url, json=payload, headers=headers) as resp:
                if resp.status == 200:
                    result = await resp.json()
                    print(f"✅ API调用成功:")
                    print(f"   频道: {result.get('channel_info', {}).get('channel_name')}")
                    print(f"   总视频数: {result.get('total_videos')}")
                    print(f"   成功提取字幕: {result.get('success_count')}")
                    print(f"   失败: {result.get('failed_count')}")
                    print(f"   耗时: {result.get('duration_seconds'):.1f}秒")
                else:
                    error_text = await resp.text()
                    raise Exception(f"API调用失败 (状态码: {resp.status}): {error_text}")
        
        # ========== 步骤4: 获取字幕内容并生成AI总结 ==========
        print("\n" + "=" * 80)
        print("步骤4: 获取字幕内容并生成AI总结")
        print("=" * 80)
        
        # 从本地数据库获取字幕内容
        feed_ids = task['feed_ids'].split(',') if task['feed_ids'] else []
        content_text = await scheduler.get_recent_subtitles_text(feed_ids)
        
        if not content_text:
            print("⚠️  警告: 未获取到字幕内容")
            content_text = "测试内容：这是一个关于科技产品评测的视频。"
        
        print(f"📝 获取到字幕内容长度: {len(content_text)} 字符")
        print(f"   内容预览: {content_text[:200]}...")
        
        # 生成AI总结
        print("\n🤖 正在生成AI总结...")
        title, content = await scheduler.generate_headline(content_text, task['prompt'])
        
        print(f"✅ AI总结生成成功:")
        print(f"   标题: {title}")
        print(f"   内容长度: {len(content)} 字符")
        print(f"   内容预览: {content[:200]}...")
        
        # ========== 步骤5: 回写D1的ai_headlines表 ==========
        print("\n" + "=" * 80)
        print("步骤5: 回写D1的ai_headlines表")
        print("=" * 80)
        
        headline_id = f"headline_test_{int(time.time())}"
        created_at = int(time.time())
        
        d1.execute("""
            INSERT INTO ai_headlines 
            (id, user_id, title, content, article_count, prompt, feed_ids, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """, [
            headline_id,
            task['user_id'],
            title,
            content,
            1,
            task['prompt'],
            task['feed_ids'],
            created_at
        ])
        
        print(f"✅ 成功写入ai_headlines表:")
        print(f"   Headline ID: {headline_id}")
        
        # 更新任务的last_executed_at
        d1.execute("""
            UPDATE scheduled_tasks 
            SET last_executed_at = ?, updated_at = ?
            WHERE id = ?
        """, [created_at, created_at, test_task_id])
        
        print(f"✅ 更新任务执行时间")
        
        # ========== 验证结果 ==========
        print("\n" + "=" * 80)
        print("验证结果")
        print("=" * 80)
        
        # 从D1读取刚创建的headline
        headlines = d1.fetch_all(
            "SELECT * FROM ai_headlines WHERE id = ?",
            [headline_id]
        )
        
        if headlines:
            headline = headlines[0]
            print(f"✅ 验证成功 - 从D1读取到headline:")
            print(f"   ID: {headline['id']}")
            print(f"   标题: {headline['title']}")
            print(f"   用户ID: {headline['user_id']}")
            print(f"   创建时间: {datetime.fromtimestamp(headline['created_at'])}")
        else:
            print("❌ 验证失败 - 未能从D1读取到headline")
        
        # 读取更新后的任务
        updated_tasks = d1.fetch_all(
            "SELECT * FROM scheduled_tasks WHERE id = ?",
            [test_task_id]
        )
        
        if updated_tasks:
            updated_task = updated_tasks[0]
            print(f"✅ 验证成功 - 任务已更新:")
            print(f"   最后执行时间: {datetime.fromtimestamp(updated_task['last_executed_at'])}")
        
        # ========== 清理测试数据 ==========
        print("\n" + "=" * 80)
        print("清理测试数据")
        print("=" * 80)
        
        cleanup = input("\n是否清理测试数据? (y/n): ").strip().lower()
        
        if cleanup == 'y':
            d1.execute("DELETE FROM ai_headlines WHERE id = ?", [headline_id])
            d1.execute("DELETE FROM scheduled_tasks WHERE id = ?", [test_task_id])
            print("✅ 测试数据已清理")
        else:
            print("⏭️  保留测试数据")
            print(f"   Headline ID: {headline_id}")
            print(f"   Task ID: {test_task_id}")
        
        print("\n" + "=" * 80)
        print("✅ 集成测试完成!")
        print("=" * 80)
        
    except Exception as e:
        print(f"\n❌ 测试失败: {e}")
        import traceback
        traceback.print_exc()
        
        # 尝试清理
        try:
            d1.execute("DELETE FROM scheduled_tasks WHERE id = ?", [test_task_id])
            print("🧹 已清理失败的任务")
        except:
            pass

if __name__ == "__main__":
    asyncio.run(test_d1_scheduler_integration())
