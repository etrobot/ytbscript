import asyncio
import os
import logging
import uuid
import time
import json
from datetime import datetime, timezone
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from openai import AsyncOpenAI
from d1_client import D1Client
from youtube_channel_processor import get_processor

# Setup logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

class TaskScheduler:
    def __init__(self):
        self.d1 = D1Client()
        self.processor = get_processor()
        api_key = os.getenv("OPENAI_API_KEY")
        if api_key:
            self.openai = AsyncOpenAI(api_key=api_key, base_url=os.getenv("OPENAI_BASE_URL"))
        else:
            self.openai = None
            logger.warning("OPENAI_API_KEY not found, AI summary features will be disabled.")
        self.scheduler = AsyncIOScheduler()

    async def init_db(self):
        """Initialize D1 tables if they don't exist"""
        logger.info("Checking D1 tables...")
        try:
            self.d1.execute("""
                CREATE TABLE IF NOT EXISTS ai_headlines (
                    id text PRIMARY KEY NOT NULL,
                    userId text NOT NULL,
                    title text NOT NULL,
                    content text NOT NULL,
                    articleCount integer DEFAULT 0 NOT NULL,
                    prompt text,
                    feedIds text,
                    customSourceIds text,
                    slides text,
                    createdAt integer
                );
            """)
            self.d1.execute("""
                CREATE TABLE IF NOT EXISTS scheduled_tasks (
                    id text PRIMARY KEY NOT NULL,
                    userId text NOT NULL,
                    taskType text NOT NULL,
                    scheduledHour integer NOT NULL,
                    feedIds text,
                    customSourceIds text,
                    prompt text,
                    isActive integer DEFAULT true NOT NULL,
                    lastExecutedAt integer,
                    createdAt integer,
                    updatedAt integer
                );
            """)
            logger.info("D1 tables check completed.")
        except Exception as e:
            logger.error(f"Failed to init DB: {e}")

    async def fetch_channel_subtitles(self, channel_id: str):
        """Fetch subtitles for a channel using the processor"""
        channel_url = f"https://www.youtube.com/channel/{channel_id}"
        # Fetch latest 5 videos to ensure we have recent content
        logger.info(f"Fetching videos for channel {channel_id}...")
        try:
            result = await self.processor.process_channel_batch(channel_url, max_videos=5)
            return result
        except Exception as e:
            logger.error(f"Error processing channel {channel_id}: {e}")
            return None

    async def get_recent_subtitles_text(self, channel_ids: list) -> str:
        """Get concatenated subtitles text from local DB for the given channels"""
        # We assume the processor has already populated the local DB
        # We'll query the local DB directly to get the text
        
        # First, ensure we have fresh data
        for cid in channel_ids:
            await self.fetch_channel_subtitles(cid.strip())

        combined_text = ""
        
        with self.processor.get_db_connection() as conn:
            cursor = conn.cursor()
            # Get videos from the last 24 hours (or just recent ones)
            # For simplicity, let's get the latest 5 videos for each channel that have subtitles
            for cid in channel_ids:
                cursor.execute("""
                    SELECT v.title, v.subtitle_json 
                    FROM videos v 
                    JOIN channels c ON v.channel_id = c.channel_id 
                    WHERE c.channel_id = ? AND v.subtitle_extracted = 1
                    ORDER BY v.upload_date DESC 
                    LIMIT 3
                """, (cid.strip(),))
                
                rows = cursor.fetchall()
                for title, subtitle_json_str in rows:
                    if not subtitle_json_str:
                        continue
                    try:
                        subtitles = json.loads(subtitle_json_str)
                        # Extract text from subtitles
                        text = " ".join([s['subtitle'] for s in subtitles])
                        combined_text += f"\n\nVideo: {title}\nContent: {text[:2000]}..." # Limit per video to avoid token limits
                    except Exception as e:
                        logger.error(f"Error parsing subtitles for {title}: {e}")
        
        return combined_text

    async def generate_headline(self, content: str, prompt: str):
        if not content:
            return "No content available for summary.", "No content"
            
        if not self.openai:
            return "AI Config Error", "OpenAI API Key not configured. summary generation skipped."

        full_prompt = f"{prompt}\n\nBased on the following video transcripts, please generate a headline and a summary article:\n\n{content}"
        
        try:
            response = await self.openai.chat.completions.create(
                model=os.getenv("OPENAI_MODEL"), 
                messages=[
                    {"role": "system", "content": "You are a helpful news editor."},
                    {"role": "user", "content": full_prompt}
                ],
                response_format={ "type": "json_object" }
            )
            
            result = response.choices[0].message.content
            # Expecting JSON with title and content
            try:
                data = json.loads(result)
                return data.get("title", "Generated Headline"), data.get("content", result)
            except:
                return "Generated Headline", result
                
        except Exception as e:
            logger.error(f"OpenAI API error: {e}")
            return "Error generating headline", str(e)

    async def run_task(self, task):
        logger.info(f"Running task {task['id']}...")
        
        feed_ids = task.get('feedIds', '').split(',') if task.get('feedIds') else []
        prompt = task.get('prompt', 'Summarize the latest news.')
        
        if not feed_ids:
            logger.warning(f"No feedIds for task {task['id']}")
            return

        # 1. Gather content
        content_text = await self.get_recent_subtitles_text(feed_ids)
        
        if not content_text:
            logger.warning(f"No subtitles found for task {task['id']}")
            return

        # 2. Generate summary
        title, content = await self.generate_headline(content_text, prompt)
        
        # 3. Save to ai_headlines
        headline_id = str(uuid.uuid4())
        created_at = int(time.time())
        
        try:
            self.d1.execute("""
                INSERT INTO ai_headlines (id, userId, title, content, articleCount, prompt, feedIds, createdAt)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """, [
                headline_id,
                task['userId'],
                title,
                content,
                1, # simple count
                prompt,
                task['feedIds'],
                created_at
            ])
            logger.info(f"Created headline {headline_id}")
            
            # 4. Update task lastExecutedAt
            self.d1.execute("""
                UPDATE scheduled_tasks SET lastExecutedAt = ? WHERE id = ?
            """, [created_at, task['id']])
            
        except Exception as e:
            logger.error(f"Failed to save headline or update task: {e}")

    async def check_schedule(self):
        logger.info("Checking schedule...")
        current_hour = datetime.now(timezone.utc).hour # Use UTC to be consistent
        # Or use local time if that's what the user expects. 
        # User metadata says "local time is ... +08:00".
        # Let's use local time of the machine running the script.
        current_hour_local = datetime.now().hour
        
        try:
            # Fetch active tasks scheduled for this hour
            # We also check if it was already executed recently (e.g. within the last 50 mins)
            # to prevent double execution if the job runs multiple times in the hour.
            # But since we run every hour, we can just check if last_executed_at is not in the current hour window.
            
            tasks = self.d1.fetch_all("SELECT * FROM scheduled_tasks WHERE isActive = 1")
            
            for task in tasks:
                scheduled_hour = task['scheduledHour']
                last_exec = task.get('lastExecutedAt')
                
                # Check if it's time to run
                # Simple logic: if scheduled_hour matches current hour
                if scheduled_hour == current_hour_local:
                    # Check if already run today
                    should_run = True
                    if last_exec:
                        last_exec_dt = datetime.fromtimestamp(last_exec)
                        if last_exec_dt.date() == datetime.now().date() and last_exec_dt.hour == current_hour_local:
                            should_run = False
                    
                    if should_run:
                        await self.run_task(task)
                        
        except Exception as e:
            logger.error(f"Error checking schedule: {e}")

    def start(self):
        # Run init_db once
        asyncio.get_event_loop().run_until_complete(self.init_db())
        
        # Add job
        self.scheduler.add_job(self.check_schedule, 'interval', hours=1, next_run_time=datetime.now())
        
        logger.info("Scheduler started. Press Ctrl+C to exit.")
        self.scheduler.start()
        
        try:
            asyncio.get_event_loop().run_forever()
        except (KeyboardInterrupt, SystemExit):
            pass

_scheduler_instance = None

def get_scheduler():
    global _scheduler_instance
    if _scheduler_instance is None:
        _scheduler_instance = TaskScheduler()
    return _scheduler_instance


if __name__ == "__main__":
    # Ensure environment variables are loaded
    from dotenv import load_dotenv
    load_dotenv()
    
    scheduler = TaskScheduler()
    scheduler.start()
