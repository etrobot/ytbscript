import asyncio
import os
from dotenv import load_dotenv
from d1_client import D1Client
from scheduler_service import TaskScheduler

load_dotenv()

def test_d1_client():
    print("Testing D1Client...")
    try:
        client = D1Client()
        print("D1Client initialized.")
        # Test a simple query
        result = client.execute("SELECT 1 as test")
        print(f"D1 Query Result: {result}")
        assert result.get("success") is True
        print("D1Client test passed.")
    except Exception as e:
        print(f"D1Client test failed: {e}")
        import traceback
        traceback.print_exc()

async def test_scheduler_init():
    print("\nTesting TaskScheduler init_db...")
    try:
        scheduler = TaskScheduler()
        print("TaskScheduler initialized.")
        await scheduler.init_db()
        print("TaskScheduler.init_db() completed.")
        
        # Verify tables exist
        client = scheduler.d1
        # D1 (SQLite) uses sqlite_schema or sqlite_master
        try:
            tables = client.fetch_all("SELECT name FROM sqlite_schema WHERE type ='table' AND name NOT LIKE 'sqlite_%';")
        except:
             tables = client.fetch_all("SELECT name FROM sqlite_master WHERE type ='table' AND name NOT LIKE 'sqlite_%';")
             
        print(f"Tables in DB: {[t['name'] for t in tables]}")
        
        print("TaskScheduler init test passed.")
    except Exception as e:
        print(f"TaskScheduler init test failed: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    test_d1_client()
    asyncio.run(test_scheduler_init())
