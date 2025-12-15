"""
Gemini Tweet Analyzer Module

Analyzes tweets with chunking support.
Returns: Summary + Flagged tweet indices with reasons.
"""

import os
import logging
import json
import re
from dataclasses import dataclass, field
from typing import Optional, List, Dict, Any

import google.generativeai as genai
from dotenv import load_dotenv

load_dotenv()

logger = logging.getLogger("analyzer")


@dataclass
class AnalysisResult:
    """Result of Gemini analysis."""
    summary: str
    themes: list[str]
    flagged_indices: list[dict] = field(default_factory=list)  # [{index: int, reason: str}, ...]
    highlighted_tweets: list[dict] = field(default_factory=list)  # Legacy, kept for compatibility
    username: str = ""
    tweet_count: int = 0
    chunks_processed: int = 1
    error: Optional[str] = None


class GeminiAnalyzer:
    """Analyzes tweets using Google Gemini API with chunking support."""

    MAX_TOKENS_PER_CHUNK = 750_000
    CHARS_PER_TOKEN = 4

    CHUNK_PROMPT = """You are a forensic analyst examining tweets from @{username}.

This is CHUNK {chunk_num} of {total_chunks}.

Each tweet has an INDEX number like [INDEX: 5]. Use these indices to identify tweets.

TASK 1: Write a brief summary of the content in this chunk (2-3 sentences).

TASK 2: Identify ALL CONTROVERSIAL tweets by their INDEX.
Look for tweets that are:
- Inflammatory, offensive, or problematic statements
- Most likely to cause public backlash or criticism
- Opinions that could be used against this person
- Content that reveals concerning views or behavior

RESPOND WITH VALID JSON ONLY (no markdown, no extra text):
{{
  "summary": "Brief summary of chunk content...",
  "flagged": [
    {{"index": 5, "reason": "Short reason why controversial"}},
    {{"index": 12, "reason": "Short reason why controversial"}}
  ]
}}

Be thorough - flag every tweet that could be considered controversial.

---

TWEETS TO ANALYZE:

{tweets}
"""

    FINAL_SUMMARY_PROMPT = """You are creating a FINAL FORENSIC REPORT for @{username}.

MATERIAL VOLUME: {total_tweets} total tweets and retweets were analyzed across {num_chunks} chunks.

Below are the chunk summaries.

YOUR TASK:
Write a ONE PARAGRAPH clinical summary (4-6 sentences max).
State that {total_tweets} tweets/retweets were analyzed, main topics, and notable patterns.
Be concise and factual.

RESPOND WITH VALID JSON ONLY:
{{
  "summary": "Your clinical summary here - 4-6 sentences, factual and objective."
}}

---

CHUNK SUMMARIES:

{chunk_analyses}
"""

    SINGLE_PROMPT = """You are a forensic analyst examining the Twitter/X activity of @{username}.

MATERIAL VOLUME: {tweet_count} total tweets and retweets are provided below for analysis.

Each tweet has an INDEX number like [INDEX: 5]. Use these indices to identify tweets.

TASK 1: Write a ONE PARAGRAPH clinical summary (4-6 sentences max).
Include: volume analyzed, main topics, and any notable patterns.
Be concise and factual.

TASK 2: Identify ALL CONTROVERSIAL tweets by their INDEX number.
Look for tweets that are:
- Inflammatory, offensive, or problematic statements
- Most likely to cause public backlash or criticism
- Opinions that could be used against this person
- Content that reveals concerning views or behavior

Be thorough - flag every tweet that could be considered controversial.

RESPOND WITH VALID JSON ONLY (no markdown, no extra text):
{{
  "summary": "Your clinical summary here - 4-6 sentences, factual and objective.",
  "flagged": [
    {{"index": 5, "reason": "Short reason why controversial"}},
    {{"index": 12, "reason": "Short reason why controversial"}}
  ]
}}

---

TWEETS:

{tweets}
"""

    def __init__(self, api_key: Optional[str] = None, model: str = "gemini-2.0-flash"):
        self.api_key = api_key or os.getenv("GEMINI_API_KEY")
        self.model_name = model
        self._model = None

        if not self.api_key:
            raise ValueError("GEMINI_API_KEY not provided")

        genai.configure(api_key=self.api_key)

    def _get_model(self):
        if self._model is None:
            self._model = genai.GenerativeModel(self.model_name)
        return self._model

    def _estimate_tokens(self, text: str) -> int:
        return len(text) // self.CHARS_PER_TOKEN

    def _chunk_tweets(self, indexed_tweets: List[Dict[str, Any]]) -> List[List[Dict[str, Any]]]:
        """Split indexed tweets into chunks that fit within token limits."""
        max_chars = self.MAX_TOKENS_PER_CHUNK * self.CHARS_PER_TOKEN
        
        # Estimate size of each tweet
        def estimate_tweet_size(tweet: dict) -> int:
            return len(str(tweet.get('text', ''))) + 100  # Add overhead for formatting
        
        total_size = sum(estimate_tweet_size(t) for t in indexed_tweets)
        if total_size <= max_chars:
            return [indexed_tweets]
        
        chunks = []
        current_chunk = []
        current_size = 0
        
        for tweet in indexed_tweets:
            tweet_size = estimate_tweet_size(tweet)
            
            if current_size + tweet_size > max_chars and current_chunk:
                chunks.append(current_chunk)
                current_chunk = [tweet]
                current_size = tweet_size
            else:
                current_chunk.append(tweet)
                current_size += tweet_size
        
        if current_chunk:
            chunks.append(current_chunk)
        
        logger.info(f"Split {len(indexed_tweets)} tweets into {len(chunks)} chunks")
        return chunks

    def _format_tweets_for_prompt(self, indexed_tweets: List[Dict[str, Any]]) -> str:
        """Format indexed tweets for the AI prompt."""
        lines = []
        for tweet in indexed_tweets:
            idx = tweet.get('index', 0)
            text = tweet.get('text', '')
            date = tweet.get('date', '')
            is_rt = tweet.get('is_retweet', False)
            
            if is_rt:
                original_author = tweet.get('original_author', 'unknown')
                line = f"[INDEX: {idx}] [RETWEET of @{original_author}] [{date}] {text}"
            else:
                line = f"[INDEX: {idx}] [{date}] {text}"
            lines.append(line)
        
        return "\n---\n".join(lines)

    def _parse_json_response(self, response_text: str) -> Dict[str, Any]:
        """Parse JSON from AI response, handling common issues."""
        text = response_text.strip()
        
        # Remove markdown code blocks if present
        if text.startswith('```'):
            # Find the end of the code block
            lines = text.split('\n')
            json_lines = []
            in_block = False
            for line in lines:
                if line.startswith('```'):
                    in_block = not in_block
                    continue
                if in_block or not line.startswith('```'):
                    json_lines.append(line)
            text = '\n'.join(json_lines).strip()
        
        # Try direct parse
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            pass
        
        # Try to find JSON object in text
        match = re.search(r'\{[\s\S]*\}', text)
        if match:
            try:
                return json.loads(match.group())
            except json.JSONDecodeError:
                pass
        
        logger.warning(f"Failed to parse JSON response: {text[:200]}...")
        return {"summary": text, "flagged": []}

    def _analyze_chunk(
        self, 
        chunk_tweets: List[Dict[str, Any]], 
        username: str, 
        chunk_num: int, 
        total_chunks: int
    ) -> tuple[str, list[dict]]:
        """Analyze a single chunk, return (summary_text, flagged_indices)."""
        formatted_tweets = self._format_tweets_for_prompt(chunk_tweets)
        
        prompt = self.CHUNK_PROMPT.format(
            username=username,
            chunk_num=chunk_num,
            total_chunks=total_chunks,
            tweets=formatted_tweets,
        )
        
        logger.info(f"Analyzing chunk {chunk_num}/{total_chunks} ({len(chunk_tweets)} tweets)")
        
        try:
            model = self._get_model()
            response = model.generate_content(prompt)
            
            if response.text:
                parsed = self._parse_json_response(response.text)
                summary = parsed.get("summary", "")
                flagged = parsed.get("flagged", [])
                logger.info(f"  Chunk {chunk_num}: flagged {len(flagged)} tweets")
                return summary, flagged
            else:
                return f"[Chunk {chunk_num} failed]", []
                
        except Exception as e:
            logger.error(f"Error analyzing chunk {chunk_num}: {e}")
            return f"[Chunk {chunk_num} error: {e}]", []

    def _create_final_summary(self, chunk_summaries: list[str], username: str, total_tweets: int) -> str:
        """Create final summary from chunk summaries."""
        combined = "\n\n".join([f"Chunk {i+1}: {s}" for i, s in enumerate(chunk_summaries)])
        
        prompt = self.FINAL_SUMMARY_PROMPT.format(
            username=username,
            total_tweets=total_tweets,
            num_chunks=len(chunk_summaries),
            chunk_analyses=combined,
        )
        
        logger.info(f"Creating final summary from {len(chunk_summaries)} chunk summaries")
        
        try:
            model = self._get_model()
            response = model.generate_content(prompt)
            if response.text:
                parsed = self._parse_json_response(response.text)
                return parsed.get("summary", response.text)
            return "Unable to generate summary."
        except Exception as e:
            logger.error(f"Error creating final summary: {e}")
            return f"Summary error: {e}"

    def analyze(
        self,
        indexed_tweets: List[Dict[str, Any]],
        username: str,
        custom_prompt: Optional[str] = None,
    ) -> AnalysisResult:
        """
        Analyze tweets, return summary + flagged indices.
        
        Args:
            indexed_tweets: List of dicts with keys: index, text, date, url, is_retweet, original_author
            username: Twitter username being analyzed
            custom_prompt: Optional custom prompt override
            
        Returns:
            AnalysisResult with summary and flagged_indices
        """
        tweet_count = len(indexed_tweets)
        
        if not indexed_tweets:
            return AnalysisResult(
                summary="No tweets to analyze.",
                themes=[],
                username=username,
                tweet_count=0,
                error="No content"
            )

        # Estimate tokens for all tweets
        total_text = " ".join(t.get('text', '') for t in indexed_tweets)
        estimated_tokens = self._estimate_tokens(total_text)
        logger.info(f"Analyzing {tweet_count} tweets (~{estimated_tokens:,} tokens)")

        # Single chunk - direct analysis
        if estimated_tokens <= self.MAX_TOKENS_PER_CHUNK:
            logger.info("Single chunk analysis")
            return self._analyze_single(indexed_tweets, username, custom_prompt)
        
        # Multi-chunk analysis
        logger.info(f"Multi-chunk analysis needed")
        chunks = self._chunk_tweets(indexed_tweets)
        
        all_flagged = []
        chunk_summaries = []
        
        for i, chunk in enumerate(chunks, 1):
            summary, flagged = self._analyze_chunk(chunk, username, i, len(chunks))
            chunk_summaries.append(summary)
            all_flagged.extend(flagged)
        
        # Create final summary
        final_summary = self._create_final_summary(chunk_summaries, username, tweet_count)
        
        logger.info(f"Total flagged tweets across all chunks: {len(all_flagged)}")
        
        return AnalysisResult(
            summary=final_summary,
            themes=[],
            flagged_indices=all_flagged,
            username=username,
            tweet_count=tweet_count,
            chunks_processed=len(chunks),
        )

    def _analyze_single(
        self,
        indexed_tweets: List[Dict[str, Any]],
        username: str,
        custom_prompt: Optional[str] = None,
    ) -> AnalysisResult:
        """Single chunk analysis - all tweets fit in one API call."""
        tweet_count = len(indexed_tweets)
        formatted_tweets = self._format_tweets_for_prompt(indexed_tweets)
        
        if custom_prompt:
            prompt = custom_prompt
            if "{tweets}" not in prompt:
                prompt += "\n\nTweets:\n{tweets}"
            prompt = prompt.format(tweets=formatted_tweets)
        else:
            prompt = self.SINGLE_PROMPT.format(
                username=username,
                tweet_count=tweet_count,
                tweets=formatted_tweets,
            )

        try:
            model = self._get_model()
            response = model.generate_content(prompt)
            
            if not response.text:
                return AnalysisResult(
                    summary="Unable to generate analysis.",
                    themes=[],
                    username=username,
                    tweet_count=tweet_count,
                    error="Empty response"
                )

            parsed = self._parse_json_response(response.text)
            summary = parsed.get("summary", "")
            flagged = parsed.get("flagged", [])
            
            logger.info(f"Single analysis complete: {len(flagged)} tweets flagged")

            return AnalysisResult(
                summary=summary,
                themes=[],
                flagged_indices=flagged,
                username=username,
                tweet_count=tweet_count,
            )

        except Exception as e:
            logger.error(f"Gemini error: {e}")
            return AnalysisResult(
                summary="",
                themes=[],
                username=username,
                tweet_count=tweet_count,
                error=f"Gemini error: {e}"
            )
