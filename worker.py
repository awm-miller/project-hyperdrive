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
import subprocess
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

# Mullvad CLI path
MULLVAD_CLI = "/usr/bin/mullvad"

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
    
    def _disconnect_vpn(self) -> bool:
        """Disconnect Mullvad VPN to allow Gemini API calls."""
        try:
            logger.info("Disconnecting VPN for Gemini call...")
            result = subprocess.run(
                [MULLVAD_CLI, "disconnect"],
                capture_output=True,
                text=True,
                timeout=30
            )
            return result.returncode == 0
        except Exception as e:
            logger.warning(f"VPN disconnect error: {e}")
            return False
    
    def _reconnect_vpn(self) -> bool:
        """Reconnect Mullvad VPN after Gemini call."""
        try:
            logger.info("Reconnecting VPN...")
            result = subprocess.run(
                [MULLVAD_CLI, "connect"],
                capture_output=True,
                text=True,
                timeout=30
            )
            return result.returncode == 0
        except Exception as e:
            logger.warning(f"VPN reconnect error: {e}")
            return False
    
    async def process_job(self, job: Job) -> None:
        """Process a single job."""
        logger.info(f"")
        logger.info(f"{'='*60}")
        logger.info(f"PROCESSING JOB: {job.id}")
        logger.info(f"  Username: @{job.username}")
        logger.info(f"  Date range: {job.start_date} to {job.end_date}")
        logger.info(f"{'='*60}")
        
        raw_tweets = []
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
                    raw_tweets.extend(rt_result.tweets)
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
                    raw_tweets.extend(search_result.tweets)
                    tweets_count = search_result.total_scraped
                
                self.queue.update_progress(
                    job, 60, f"Got {tweets_count} tweets",
                    tweets_scraped=tweets_count,
                    retweets_scraped=retweets_count
                )
                logger.info(f"[Step 2] Got {tweets_count} tweets/replies")
            
            # Check if we got any content
            if not raw_tweets:
                self.queue.fail_job(job, "No tweets found")
                return
            
            # Step 3: Convert to indexed tweet format for analyzer
            self.queue.update_progress(job, 70, "Analyzing with Gemini...")
            logger.info(f"[Step 3] Analyzing {len(raw_tweets)} tweets with Gemini...")
            
            # Build indexed tweets array
            indexed_tweets = []
            for idx, t in enumerate(raw_tweets):
                # Extract tweet ID from URL or use id attribute
                tweet_id = getattr(t, 'id', '')
                if not tweet_id:
                    # Try to extract from URL: https://twitter.com/user/status/ID
                    url = getattr(t, 'url', '')
                    if '/status/' in url:
                        tweet_id = url.split('/status/')[-1].split('?')[0]
                
                tweet_dict = {
                    "index": idx,
                    "id": tweet_id,
                    "text": getattr(t, 'content', ''),
                    "date": getattr(t, 'timestamp', ''),
                    "url": getattr(t, 'url', ''),
                    "is_retweet": getattr(t, 'is_retweet', False),
                    "original_author": getattr(t, 'original_author', None),
                    "images": getattr(t, 'images', []),
                    "flagged": False,
                    "flag_reason": None,
                }
                indexed_tweets.append(tweet_dict)
            
            logger.info(f"Built indexed tweets array: {len(indexed_tweets)} tweets")
            
            # Disconnect VPN before Gemini call (VPN may block Google API)
            self._disconnect_vpn()
            
            try:
                # Run Gemini analysis with indexed tweets
                analyzer = GeminiAnalyzer(api_key=self.gemini_key)
                analysis_result = analyzer.analyze(
                    indexed_tweets=indexed_tweets,
                    username=job.username,
                    custom_prompt=job.custom_prompt,
                )
            finally:
                # Always reconnect VPN after Gemini call
                self._reconnect_vpn()
            
            self.queue.update_progress(job, 90, "Finalizing...")
            
            # Merge flags into indexed tweets
            flagged_count = 0
            for flag_info in analysis_result.flagged_indices:
                idx = flag_info.get("index")
                reason = flag_info.get("reason", "")
                if idx is not None and 0 <= idx < len(indexed_tweets):
                    indexed_tweets[idx]["flagged"] = True
                    indexed_tweets[idx]["flag_reason"] = reason
                    flagged_count += 1
            
            logger.info(f"Merged flags: {flagged_count} tweets flagged out of {len(indexed_tweets)}")
            
            # Sort tweets: flagged first, then by date
            sorted_tweets = sorted(
                indexed_tweets,
                key=lambda t: (not t["flagged"], t.get("date", "")),
            )
            
            # Build legacy highlighted_tweets for backward compatibility
            highlighted_tweets = []
            for t in sorted_tweets:
                if t["flagged"]:
                    highlighted_tweets.append({
                        "text": t["text"],
                        "reason": t["flag_reason"],
                        "url": t["url"],
                        "images": t.get("images", []),
                    })
            
            # Complete the job with all tweets
            self.queue.complete_job(
                job=job,
                analysis=analysis_result.summary,
                themes=[],
                highlighted_tweets=highlighted_tweets,
                tweets_scraped=tweets_count,
                retweets_scraped=retweets_count,
                all_tweets=sorted_tweets,
            )
            
            logger.info(f"")
            logger.info(f"{'='*60}")
            logger.info(f"JOB COMPLETE: {job.id}")
            logger.info(f"  Tweets: {tweets_count}, Retweets: {retweets_count}")
            logger.info(f"  Total content: {len(sorted_tweets)}")
            logger.info(f"  Flagged: {flagged_count}")
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

