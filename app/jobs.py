"""
Job Queue System using Redis

Handles job creation, status tracking, and results storage.
"""

import json
import uuid
import logging
from datetime import datetime
from typing import Optional, List, Dict, Any
from dataclasses import dataclass, field, asdict
from enum import Enum

import redis
from redis import Redis

logger = logging.getLogger("jobs")


class JobStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"


@dataclass
class Job:
    """Represents an analysis job."""
    id: str
    username: str
    status: JobStatus = JobStatus.PENDING
    
    # Request parameters
    start_date: Optional[str] = None
    end_date: Optional[str] = None
    include_tweets: bool = True
    include_retweets: bool = True
    include_replies: bool = True
    custom_prompt: Optional[str] = None
    
    # Progress tracking
    progress: int = 0  # 0-100
    current_step: str = "Queued"
    tweets_scraped: int = 0
    retweets_scraped: int = 0
    
    # Results
    analysis: str = ""
    themes: List[str] = field(default_factory=list)
    highlighted_tweets: List[Dict[str, Any]] = field(default_factory=list)
    error: Optional[str] = None
    
    # Timestamps
    created_at: str = ""
    started_at: Optional[str] = None
    completed_at: Optional[str] = None
    
    # Worker info
    worker_id: Optional[str] = None
    
    def to_dict(self) -> dict:
        """Convert to dictionary for Redis storage."""
        data = asdict(self)
        data['status'] = self.status.value
        return data
    
    @classmethod
    def from_dict(cls, data: dict) -> 'Job':
        """Create from dictionary."""
        data['status'] = JobStatus(data.get('status', 'pending'))
        return cls(**data)


class JobQueue:
    """Redis-backed job queue."""
    
    JOBS_KEY = "hyperdrive:jobs"  # Hash of all jobs
    QUEUE_KEY = "hyperdrive:queue"  # List of pending job IDs
    
    def __init__(self, redis_url: str = "redis://localhost:6379"):
        """
        Initialize the job queue.
        
        Args:
            redis_url: Redis connection URL
        """
        self.redis = Redis.from_url(redis_url, decode_responses=True)
        logger.info(f"JobQueue connected to Redis: {redis_url}")
    
    def create_job(
        self,
        username: str,
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
        include_tweets: bool = True,
        include_retweets: bool = True,
        include_replies: bool = True,
        custom_prompt: Optional[str] = None,
    ) -> Job:
        """
        Create a new job and add it to the queue.
        
        Returns:
            The created Job object
        """
        job = Job(
            id=str(uuid.uuid4())[:8],  # Short ID for readability
            username=username,
            start_date=start_date,
            end_date=end_date,
            include_tweets=include_tweets,
            include_retweets=include_retweets,
            include_replies=include_replies,
            custom_prompt=custom_prompt,
            created_at=datetime.now().isoformat(),
        )
        
        # Store job data
        self.redis.hset(self.JOBS_KEY, job.id, json.dumps(job.to_dict()))
        
        # Add to pending queue
        self.redis.rpush(self.QUEUE_KEY, job.id)
        
        logger.info(f"Created job {job.id} for @{username}")
        return job
    
    def get_job(self, job_id: str) -> Optional[Job]:
        """Get a job by ID."""
        data = self.redis.hget(self.JOBS_KEY, job_id)
        if not data:
            return None
        return Job.from_dict(json.loads(data))
    
    def update_job(self, job: Job) -> None:
        """Update job data in Redis."""
        self.redis.hset(self.JOBS_KEY, job.id, json.dumps(job.to_dict()))
    
    def get_next_job(self, worker_id: str) -> Optional[Job]:
        """
        Get the next pending job from the queue.
        Marks it as running with the worker ID.
        
        Args:
            worker_id: ID of the worker claiming the job
            
        Returns:
            Job if one is available, None otherwise
        """
        # Pop from queue (blocking with timeout)
        result = self.redis.blpop(self.QUEUE_KEY, timeout=5)
        if not result:
            return None
        
        _, job_id = result
        job = self.get_job(job_id)
        
        if job:
            job.status = JobStatus.RUNNING
            job.started_at = datetime.now().isoformat()
            job.worker_id = worker_id
            job.current_step = "Starting..."
            self.update_job(job)
            logger.info(f"Worker {worker_id} claimed job {job.id}")
        
        return job
    
    def complete_job(
        self,
        job: Job,
        analysis: str,
        themes: List[str],
        highlighted_tweets: List[Dict[str, Any]],
        tweets_scraped: int,
        retweets_scraped: int,
    ) -> None:
        """Mark a job as completed with results."""
        job.status = JobStatus.COMPLETED
        job.completed_at = datetime.now().isoformat()
        job.progress = 100
        job.current_step = "Complete"
        job.analysis = analysis
        job.themes = themes
        job.highlighted_tweets = highlighted_tweets
        job.tweets_scraped = tweets_scraped
        job.retweets_scraped = retweets_scraped
        self.update_job(job)
        logger.info(f"Job {job.id} completed")
    
    def fail_job(self, job: Job, error: str) -> None:
        """Mark a job as failed."""
        job.status = JobStatus.FAILED
        job.completed_at = datetime.now().isoformat()
        job.current_step = "Failed"
        job.error = error
        self.update_job(job)
        logger.error(f"Job {job.id} failed: {error}")
    
    def update_progress(
        self,
        job: Job,
        progress: int,
        current_step: str,
        tweets_scraped: int = 0,
        retweets_scraped: int = 0,
    ) -> None:
        """Update job progress."""
        job.progress = progress
        job.current_step = current_step
        job.tweets_scraped = tweets_scraped
        job.retweets_scraped = retweets_scraped
        self.update_job(job)
    
    def list_jobs(self, limit: int = 50) -> List[Job]:
        """Get recent jobs."""
        all_jobs = self.redis.hgetall(self.JOBS_KEY)
        jobs = []
        for job_data in all_jobs.values():
            try:
                jobs.append(Job.from_dict(json.loads(job_data)))
            except Exception as e:
                logger.error(f"Error parsing job: {e}")
        
        # Sort by created_at descending
        jobs.sort(key=lambda j: j.created_at, reverse=True)
        return jobs[:limit]
    
    def get_queue_length(self) -> int:
        """Get number of pending jobs."""
        return self.redis.llen(self.QUEUE_KEY)
    
    def clear_all(self) -> None:
        """Clear all jobs (for testing)."""
        self.redis.delete(self.JOBS_KEY)
        self.redis.delete(self.QUEUE_KEY)
        logger.warning("Cleared all jobs")

