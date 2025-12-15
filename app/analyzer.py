"""
Gemini Tweet Analyzer Module

Analyzes tweets with chunking support.
Returns: Summary + Highlighted tweets picked by AI.
"""

import os
import logging
import json
from dataclasses import dataclass, field
from typing import Optional

import google.generativeai as genai
from dotenv import load_dotenv

load_dotenv()

logger = logging.getLogger("analyzer")


@dataclass
class AnalysisResult:
    """Result of Gemini analysis."""
    summary: str
    themes: list[str]
    highlighted_tweets: list[dict] = field(default_factory=list)
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

TASK 1: Provide a factual summary of the content in this chunk.
- Key topics discussed
- Events or news referenced
- Notable patterns

TASK 2: Identify the MOST CONTROVERSIAL tweets in this chunk.
Look for tweets that are:
- Most likely to cause public backlash or criticism
- Inflammatory, offensive, or problematic statements
- Opinions that could be used against this person
- Content that reveals concerning views

Each tweet in the data includes a URL in brackets like [URL: https://...].

FORMAT YOUR RESPONSE EXACTLY LIKE THIS:

## CHUNK ANALYSIS
[Factual summary of content - 1-2 paragraphs]

## CONTROVERSIAL TWEETS IN THIS CHUNK
1. "[exact tweet text]" | URL: [copy URL from data] | [why controversial]
2. "[exact tweet text]" | URL: [copy URL from data] | [why controversial]
... (include all controversial tweets found in this chunk)

---

TWEETS TO ANALYZE:

{tweets}
"""

    FINAL_SUMMARY_PROMPT = """You are creating a FINAL FORENSIC REPORT for @{username}.

MATERIAL VOLUME: {total_tweets} total tweets and retweets were analyzed across {num_chunks} chunks.

Below are the analyses from each chunk.

YOUR TASK:
Write a ONE PARAGRAPH clinical summary (4-6 sentences max).
State that {total_tweets} tweets/retweets were analyzed, the date range, main topics, and notable patterns.
Be concise. The controversial tweets are already identified in the chunk analyses - do NOT repeat them.

FORMAT:
## ANALYSIS SUMMARY
[One concise paragraph - 4-6 sentences]

---

CHUNK ANALYSES:

{chunk_analyses}
"""

    SINGLE_PROMPT = """You are a forensic analyst examining the Twitter/X activity of @{username}.

MATERIAL VOLUME: {tweet_count} total tweets and retweets are provided below for analysis.

TASK 1: Write a ONE PARAGRAPH clinical summary (4-6 sentences max).
Include: volume analyzed, date range, main topics, and any notable patterns.
Be concise and factual.

TASK 2: Identify ALL CONTROVERSIAL tweets in the material.
Look for tweets that are:
- Most likely to cause public backlash or criticism
- Inflammatory, offensive, or problematic statements
- Opinions that could be used against this person
- Content that reveals concerning views or behavior

Be thorough - include every tweet that could be considered controversial. Could be 5, 10, 20 or more.

Each tweet in the data includes a URL in brackets like [URL: https://...].

FORMAT YOUR RESPONSE EXACTLY LIKE THIS:

## ANALYSIS SUMMARY
[Your clinical summary here - factual, objective, like an intelligence briefing]

## CONTROVERSIAL TWEETS
1. "[EXACT tweet text]" | URL: [copy the URL from the data] | [why controversial]
2. "[EXACT tweet text]" | URL: [copy the URL from the data] | [why controversial]
... (include ALL controversial tweets found)

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

    def _chunk_tweets(self, compiled_tweets: str) -> list[str]:
        max_chars = self.MAX_TOKENS_PER_CHUNK * self.CHARS_PER_TOKEN
        
        if len(compiled_tweets) <= max_chars:
            return [compiled_tweets]
        
        chunks = []
        tweets = compiled_tweets.split('\n---\n')
        
        current_chunk = []
        current_length = 0
        
        for tweet in tweets:
            tweet_length = len(tweet) + 5
            
            if current_length + tweet_length > max_chars:
                if current_chunk:
                    chunks.append('\n---\n'.join(current_chunk))
                current_chunk = [tweet]
                current_length = tweet_length
            else:
                current_chunk.append(tweet)
                current_length += tweet_length
        
        if current_chunk:
            chunks.append('\n---\n'.join(current_chunk))
        
        logger.info(f"Split {len(tweets)} tweets into {len(chunks)} chunks")
        return chunks

    def _extract_highlighted_tweets(self, analysis_text: str) -> list[dict]:
        """Extract highlighted tweets from analysis response."""
        import re
        tweets = []
        lines = analysis_text.split('\n')
        in_highlights = False
        
        for line in lines:
            line_stripped = line.strip()
            
            # Detect highlights section (multiple possible headers)
            if any(x in line.upper() for x in ['HIGHLIGHTED TWEETS', 'NOTABLE TWEETS', 'CONTROVERSIAL TWEETS', 'TOP 3']):
                in_highlights = True
                continue
            
            # Stop at next section
            if in_highlights and line_stripped.startswith('##'):
                break
            
            # Extract numbered tweets
            if in_highlights and line_stripped and line_stripped[0].isdigit():
                # New format: 1. "tweet text" | URL: https://... | reason
                # Also handle old format: 1. "tweet" - reason
                
                # Remove the leading number
                content = re.sub(r'^\d+[\.\)]\s*', '', line_stripped)
                
                # Try multiple URL patterns
                url = ""
                # Pattern 1: | URL: https://...
                url_match = re.search(r'\|\s*URL:\s*(https?://[^\s|]+)', content)
                if url_match:
                    url = url_match.group(1).strip()
                else:
                    # Pattern 2: [URL: https://...]
                    url_match = re.search(r'\[URL:\s*(https?://[^\]]+)\]', content)
                    if url_match:
                        url = url_match.group(1).strip()
                    else:
                        # Pattern 3: any twitter/x.com URL
                        url_match = re.search(r'(https?://(?:twitter\.com|x\.com)/[^\s|,\]]+)', content)
                        if url_match:
                            url = url_match.group(1).strip()
                
                # Extract tweet text (between quotes or before first |)
                if content.startswith('"'):
                    text_match = re.match(r'"([^"]+)"', content)
                    tweet_text = text_match.group(1) if text_match else ""
                else:
                    # No quotes - take everything before first |
                    tweet_text = content.split('|')[0].strip().strip('"')
                
                # Extract reason (after last |, or after - if old format)
                parts = content.split('|')
                if len(parts) >= 3:
                    reason = parts[-1].strip()
                elif ' - ' in content or ' – ' in content or ' — ' in content:
                    reason = re.split(r'\s*[-–—]\s*', content)[-1]
                else:
                    reason = ""
                
                if len(tweet_text) > 10:
                    tweets.append({
                        "text": tweet_text,
                        "url": url,
                        "reason": reason
                    })
        
        return tweets

    def _extract_themes(self, analysis_text: str) -> list[str]:
        themes = []
        lines = analysis_text.split('\n')
        in_themes = False
        
        for line in lines:
            line_lower = line.lower().strip()
            
            if 'key themes' in line_lower or 'main themes' in line_lower:
                in_themes = True
                continue
            
            if in_themes and line.strip().startswith('##'):
                break
            
            if in_themes and line.strip().startswith(('-', '*', '•')):
                theme = line.strip().lstrip('-*•').strip()
                theme = theme.replace('**', '')
                if theme and len(theme) < 100:
                    themes.append(theme)
        
        return themes[:10]

    def _analyze_chunk(self, chunk: str, username: str, chunk_num: int, total_chunks: int) -> tuple[str, list[dict]]:
        """Analyze a single chunk, return (analysis_text, highlighted_tweets)."""
        prompt = self.CHUNK_PROMPT.format(
            username=username,
            chunk_num=chunk_num,
            total_chunks=total_chunks,
            tweets=chunk,
        )
        
        logger.info(f"Analyzing chunk {chunk_num}/{total_chunks}")
        
        try:
            model = self._get_model()
            response = model.generate_content(prompt)
            
            if response.text:
                highlighted = self._extract_highlighted_tweets(response.text)
                logger.info(f"  Chunk {chunk_num}: extracted {len(highlighted)} highlighted tweets")
                return response.text, highlighted
            else:
                return f"[Chunk {chunk_num} failed]", []
                
        except Exception as e:
            logger.error(f"Error analyzing chunk {chunk_num}: {e}")
            return f"[Chunk {chunk_num} error: {e}]", []

    def _create_final_summary(self, chunk_analyses: list[str], username: str, total_tweets: int) -> str:
        """Create final summary from chunk analyses."""
        combined = "\n\n".join([f"=== CHUNK {i+1} ===\n{a}" for i, a in enumerate(chunk_analyses)])
        
        prompt = self.FINAL_SUMMARY_PROMPT.format(
            username=username,
            total_tweets=total_tweets,
            num_chunks=len(chunk_analyses),
            chunk_analyses=combined,
        )
        
        logger.info(f"Creating final summary from {len(chunk_analyses)} chunks")
        
        try:
            model = self._get_model()
            response = model.generate_content(prompt)
            return response.text if response.text else "Unable to generate summary."
        except Exception as e:
            logger.error(f"Error creating final summary: {e}")
            return f"Summary error: {e}"

    def analyze(
        self,
        compiled_tweets: str,
        username: str,
        tweet_count: int,
        custom_prompt: Optional[str] = None,
    ) -> AnalysisResult:
        """Analyze tweets, return summary + highlighted tweets."""
        
        if not compiled_tweets.strip():
            return AnalysisResult(
                summary="No tweets to analyze.",
                themes=[],
                username=username,
                tweet_count=0,
                error="No content"
            )

        estimated_tokens = self._estimate_tokens(compiled_tweets)
        logger.info(f"Analyzing {tweet_count} tweets (~{estimated_tokens:,} tokens)")

        # Single chunk - direct analysis
        if estimated_tokens <= self.MAX_TOKENS_PER_CHUNK:
            logger.info("Single chunk analysis")
            return self._analyze_single(compiled_tweets, username, tweet_count, custom_prompt)
        
        # Multi-chunk analysis
        logger.info(f"Multi-chunk analysis needed")
        chunks = self._chunk_tweets(compiled_tweets)
        
        all_highlighted = []
        chunk_analyses = []
        
        for i, chunk in enumerate(chunks, 1):
            analysis, highlighted = self._analyze_chunk(chunk, username, i, len(chunks))
            chunk_analyses.append(analysis)
            all_highlighted.extend(highlighted)
        
        # Create final summary
        final_summary = self._create_final_summary(chunk_analyses, username, tweet_count)
        themes = self._extract_themes(final_summary)
        
        return AnalysisResult(
            summary=final_summary,
            themes=themes,
            highlighted_tweets=all_highlighted,
            username=username,
            tweet_count=tweet_count,
            chunks_processed=len(chunks),
        )

    def _analyze_single(
        self,
        compiled_tweets: str,
        username: str,
        tweet_count: int,
        custom_prompt: Optional[str] = None,
    ) -> AnalysisResult:
        """Single chunk analysis."""
        
        if custom_prompt:
            prompt = custom_prompt
            if "{tweets}" not in prompt:
                prompt += "\n\nTweets:\n{tweets}"
            prompt = prompt.format(tweets=compiled_tweets)
        else:
            prompt = self.SINGLE_PROMPT.format(
                username=username,
                tweet_count=tweet_count,
                tweets=compiled_tweets,
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

            text = response.text
            themes = self._extract_themes(text)
            highlighted = self._extract_highlighted_tweets(text)
            
            # Extract just the summary part (before highlighted tweets)
            summary = text
            if "## HIGHLIGHTED TWEETS" in text:
                summary = text.split("## HIGHLIGHTED TWEETS")[0].strip()

            return AnalysisResult(
                summary=summary,
                themes=themes,
                highlighted_tweets=highlighted,
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
