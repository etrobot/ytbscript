import asyncio
import os
import sqlite3
import json
import time
from unittest.mock import MagicMock, AsyncMock
from dotenv import load_dotenv
from scheduler_service import TaskScheduler
from youtube_channel_processor import YouTubeChannelProcessor

load_dotenv()

TEST_DB_PATH = "test_youtube_channels.db"

def setup_test_db():
    if os.path.exists(TEST_DB_PATH):
        os.remove(TEST_DB_PATH)
    
    processor = YouTubeChannelProcessor(db_path=TEST_DB_PATH)
    
    # Insert dummy data
    with sqlite3.connect(TEST_DB_PATH) as conn:
        cursor = conn.cursor()
        
        # Channel
        cursor.execute('''
            INSERT INTO channels (channel_id, channel_name, channel_url, last_processed)
            VALUES (?, ?, ?, ?)
        ''', ('UC_TEST', 'Test Channel', 'https://youtube.com/channel/UC_TEST', datetime.now()))
        
        # Video with subtitles
        subtitles = [{'start': '00:00:01.000', 'end': '00:00:05.000', 'subtitle': 'This is a test video content.'}]
        
        cursor.execute('''
            INSERT INTO videos 
            (video_id, channel_id, title, url, duration, upload_date, uploader, subtitle_extracted, subtitle_language, subtitle_json)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ''', (
            'VID_TEST',
            'UC_TEST',
            'Test Video',
            'https://youtube.com/watch?v=VID_TEST',
            100,
            '20230101',
            'Test Channel',
            True,
            'en',
            json.dumps(subtitles)
        ))
        conn.commit()
    
    return processor

from datetime import datetime

async def test_flow():
    print("Setting up test environment...")
    processor = setup_test_db()
    
    scheduler = TaskScheduler()
    # Override processor with our test one
    scheduler.processor = processor
    
    # Mock OpenAI
    mock_openai = AsyncMock()
    mock_response = MagicMock()
    mock_response.choices = [MagicMock(message=MagicMock(content=json.dumps({
        "title": "AI Generated Headline",
        "content": "AI Generated Summary Content"
    })))]
    mock_openai.chat.completions.create.return_value = mock_response
    scheduler.openai = mock_openai
    
    # Mock fetch_channel_subtitles to avoid network calls
    scheduler.fetch_channel_subtitles = AsyncMock(return_value=None)
    
    print("Initialized Scheduler with mocks.")
    
    # Define a test task
    task = {
        'id': 'TASK_TEST',
        'user_id': 'USER_TEST',
        'feed_ids': 'UC_TEST',
        'prompt': 'Summarize this.',
        'scheduled_hour': 10
    }
    
    print(f"Running task: {task['id']}")
    await scheduler.run_task(task)
    
    # Verify results in D1
    print("Verifying results in D1...")
    # We expect a new entry in ai_headlines
    # Since we don't know the ID, we search by user_id
    # Note: D1Client is real, so we are checking the real D1 database.
    # Be careful not to pollute it too much, but for dev it's fine.
    
    try:
        headlines = scheduler.d1.fetch_all("SELECT * FROM ai_headlines WHERE user_id = ?", ['USER_TEST'])
        print(f"Found {len(headlines)} headlines for USER_TEST")
        
        found = False
        for h in headlines:
            if h['title'] == "AI Generated Headline":
                print("SUCCESS: Found generated headline!")
                print(f"Headline ID: {h['id']}")
                print(f"Content: {h['content']}")
                
                # Cleanup
                scheduler.d1.execute("DELETE FROM ai_headlines WHERE id = ?", [h['id']])
                print("Cleaned up test headline.")
                found = True
                break
        
        if not found:
            print("FAILURE: Did not find the generated headline.")
            
    except Exception as e:
        print(f"Error verifying D1: {e}")

    # Cleanup local DB
    if os.path.exists(TEST_DB_PATH):
        os.remove(TEST_DB_PATH)
        print("Cleaned up local test DB.")

if __name__ == "__main__":
    asyncio.run(test_flow())
