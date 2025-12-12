"""
Hyperdrive Worker

Standalone worker process that:
1. Polls Redis for pending jobs
2. Processes analysis jobs (scraping + Gemini)
3. Updates job progress
4. Handles VPN rotation independently

Run with: python worker.py --id worker1
"""

import asyncio
import argparse
import logging
import os
import sys
from datetime import datetime

from dotenv import load_dotenv

# Add app to path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from app.jobs import JobQueue, Job, JobStatus
from app.scraper_timeline import NitterTimelineScraper
from app.scraper_search import NitterSearchScraper
from app.analyzer import GeminiAnalyzer

load_dotenv()

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(name)s: %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
)
logger = logging.getLogger("worker")


class Worker:
    """Job processing worker."""
    
    def __init__(
        self,
        worker_id: str,
        redis_url: str = "redis://localhost:6379",
        nitter_url: str = "http://localhost:8080",
    ):
        self.worker_id = worker_id
        self.nitter_url = nitter_url
        self.queue = JobQueue(redis_url)
        self.running = True
        
        # Get Gemini key
        self.gemini_key = os.getenv("GEMINI_API_KEY")
        if not self.gemini_key:
            raise ValueError("GEMINI_API_KEY not set")
        
        logger.info(f"Worker {worker_id} initialized")
        logger.info(f"  Nitter URL: {nitter_url}")
        logger.info(f"  Redis URL: {redis_url}")
    
    async def process_job(self, job: Job) -> None:
        """Process a single job."""
        logger.info(f"")
        logger.info(f"{'='*60}")
        logger.info(f"PROCESSING JOB: {job.id}")
        logger.info(f"  Username: @{job.username}")
        logger.info(f"  Date range: {job.start_date} to {job.end_date}")
        logger.info(f"{'='*60}")
        
        all_tweets = []
        retweets_count = 0
        tweets_count = 0
        
        try:
            # Parse dates
            start_date = None
            end_date = None
            if job.start_date:
                start_date = datetime.strptime(job.start_date, "%Y-%m-%d")
            if job.end_date:
                end_date = datetime.strptime(job.end_date, "%Y-%m-%d")
            
            # Step 1: Scrape retweets from timeline
            if job.include_retweets:
                self.queue.update_progress(job, 10, "Scraping retweets...")
                logger.info("[Step 1] Scraping retweets...")
                
                async with NitterTimelineScraper(
                    nitter_url=self.nitter_url,
                    delay_seconds=0.5,
                    max_retweets=5000,
                ) as scraper:
                    rt_result = await scraper.scrape_retweets(username=job.username)
                    all_tweets.extend(rt_result.tweets)
                    retweets_count = rt_result.total_scraped
                
                self.queue.update_progress(
                    job, 30, f"Got {retweets_count} retweets",
                    retweets_scraped=retweets_count
                )
                logger.info(f"[Step 1] Got {retweets_count} retweets")
            
            # Step 2: Scrape tweets/replies from search
            if job.include_tweets or job.include_replies:
                self.queue.update_progress(job, 40, "Scraping tweets...")
                logger.info("[Step 2] Scraping tweets/replies...")
                
                async with NitterSearchScraper(
                    nitter_url=self.nitter_url,
                    delay_seconds=0.5,
                    max_tweets=5000,
                ) as scraper:
                    search_result = await scraper.scrape_user(
                        username=job.username,
                        start_date=start_date,
                        end_date=end_date,
                        include_retweets=False,
                        include_replies=job.include_replies,
                    )
                    all_tweets.extend(search_result.tweets)
                    tweets_count = search_result.total_scraped
                
                self.queue.update_progress(
                    job, 60, f"Got {tweets_count} tweets",
                    tweets_scraped=tweets_count,
                    retweets_scraped=retweets_count
                )
                logger.info(f"[Step 2] Got {tweets_count} tweets/replies")
            
            # Check if we got any content
            if not all_tweets:
                self.queue.fail_job(job, "No tweets found")
                return
            
            # Step 3: Analyze with Gemini
            self.queue.update_progress(job, 70, "Analyzing with Gemini...")
            logger.info(f"[Step 3] Analyzing {len(all_tweets)} tweets with Gemini...")
            
            # Build tweet lookup by URL for image matching
            url_to_images = {}
            for t in all_tweets:
                url = getattr(t, 'url', '')
                if url:
                    url_to_images[url] = getattr(t, 'images', [])
            
            # Compile tweets - include URL for each tweet
            # No truncation - the analyzer handles chunking internally
            compiled_lines = []
            for t in all_tweets:
                url = getattr(t, 'url', '')
                if getattr(t, 'is_retweet', False):
                    original_author = getattr(t, 'original_author', 'unknown')
                    line = f"[RETWEET of @{original_author}] [{t.timestamp}] {t.content} [URL: {url}]"
                else:
                    line = f"[{t.timestamp}] {t.content} [URL: {url}]"
                compiled_lines.append(line)
            compiled = "\n---\n".join(compiled_lines)
            
            logger.info(f"Compiled {len(all_tweets)} tweets into {len(compiled):,} characters")
            
            # Run Gemini analysis
            analyzer = GeminiAnalyzer(api_key=self.gemini_key)
            analysis_result = analyzer.analyze(
                compiled_tweets=compiled,
                username=job.username,
                tweet_count=len(all_tweets),
                custom_prompt=job.custom_prompt,
            )
            
            self.queue.update_progress(job, 90, "Finalizing...")
            
            # Process highlighted tweets - extract URLs and match images
            highlighted_with_urls = []
            for ht in analysis_result.highlighted_tweets:
                text = ht.get("text", "")
                reason = ht.get("reason", "")
                url = ht.get("url", "")  # Gemini should return this now
                
                # Get images for this URL
                images = url_to_images.get(url, []) if url else []
                
                highlighted_with_urls.append({
                    "text": text,
                    "reason": reason,
                    "url": url,
                    "images": images,
                })
            
            # Complete the job
            self.queue.complete_job(
                job=job,
                analysis=analysis_result.summary,
                themes=analysis_result.themes,
                highlighted_tweets=highlighted_with_urls,
                tweets_scraped=tweets_count,
                retweets_scraped=retweets_count,
            )
            
            logger.info(f"")
            logger.info(f"{'='*60}")
            logger.info(f"JOB COMPLETE: {job.id}")
            logger.info(f"  Tweets: {tweets_count}, Retweets: {retweets_count}")
            logger.info(f"  Themes: {len(analysis_result.themes)}")
            logger.info(f"  Highlights: {len(highlighted_with_urls)}")
            logger.info(f"{'='*60}")
            
        except Exception as e:
            logger.exception(f"Job {job.id} failed")
            self.queue.fail_job(job, str(e))
    
    async def run(self) -> None:
        """Main worker loop."""
        logger.info(f"")
        logger.info(f"{'='*60}")
        logger.info(f"WORKER {self.worker_id} STARTING")
        logger.info(f"{'='*60}")
        logger.info(f"Polling for jobs...")
        
        # Register worker
        self.queue.register_worker(self.worker_id, self.nitter_url)
        
        while self.running:
            try:
                # Send heartbeat
                self.queue.worker_heartbeat(self.worker_id, "idle")
                
                # Get next job (blocks for up to 5 seconds)
                job = self.queue.get_next_job(self.worker_id)
                
                if job:
                    # Update heartbeat with job info
                    self.queue.worker_heartbeat(self.worker_id, "busy", job.id)
                    await self.process_job(job)
                    self.queue.worker_heartbeat(self.worker_id, "idle")
                else:
                    # No job available, continue polling
                    pass
                    
            except KeyboardInterrupt:
                logger.info("Shutting down...")
                self.running = False
            except Exception as e:
                logger.exception(f"Worker error: {e}")
                await asyncio.sleep(5)  # Wait before retrying
        
        logger.info(f"Worker {self.worker_id} stopped")


def main():
    parser = argparse.ArgumentParser(description="Hyperdrive Worker")
    parser.add_argument("--id", default="worker1", help="Worker ID")
    parser.add_argument("--redis", default="redis://localhost:6379", help="Redis URL")
    parser.add_argument("--nitter", default="http://localhost:8080", help="Nitter URL")
    args = parser.parse_args()
    
    worker = Worker(
        worker_id=args.id,
        redis_url=args.redis,
        nitter_url=args.nitter,
    )
    
    asyncio.run(worker.run())


if __name__ == "__main__":
    main()

