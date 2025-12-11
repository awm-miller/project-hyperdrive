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

    CHUNK_PROMPT = """You are analyzing tweets from @{username}.

This is CHUNK {chunk_num} of {total_chunks}.

TASK 1: Analyze the themes and content in these tweets.

TASK 2: Pick out the 10-15 MOST NOTABLE/INTERESTING tweets from this chunk.
These should be tweets that are:
- Particularly insightful or revealing
- Controversial or attention-grabbing
- Representative of key themes
- Unusually engaging (high likes/retweets mentioned)
- Memorable quotes or statements

FORMAT YOUR RESPONSE EXACTLY LIKE THIS:

## ANALYSIS
[Your analysis of themes, tone, key points - 2-3 paragraphs]

## HIGHLIGHTED TWEETS
1. "[exact tweet text]" - [brief reason why notable]
2. "[exact tweet text]" - [brief reason why notable]
... (10-15 tweets)

---

TWEETS TO ANALYZE:

{tweets}
"""

    FINAL_SUMMARY_PROMPT = """You are creating a FINAL REPORT for @{username} based on {total_tweets} tweets.

Below are analyses from {num_chunks} chunks.

YOUR TASK: Write ONE PUNCHY PARAGRAPH (4-6 sentences max) that captures the ESSENCE of this account.

Think of it like a "juicer" - the concentrated extract of who this person is online.
- What defines them?
- What do they care about most? 
- What's their vibe?
- Any spicy takes or patterns?

Be direct, insightful, maybe a little provocative. No fluff. No bullet points in the summary.

After the paragraph, list 3-5 KEY THEMES as bullet points.

FORMAT:
## THE JUICER
[Your punchy paragraph here]

## KEY THEMES
- [theme 1]
- [theme 2]
...

---

CHUNK ANALYSES:

{chunk_analyses}
"""

    SINGLE_PROMPT = """You are analyzing tweets from @{username}.

TASK 1: Write ONE PUNCHY PARAGRAPH (4-6 sentences) that captures the ESSENCE of this account.
Think of it like a "juicer" - the concentrated extract of who this person is online.
Be direct, insightful, maybe provocative. No fluff.

TASK 2: List 3-5 KEY THEMES as bullet points.

TASK 3: Pick out the 15-20 MOST NOTABLE tweets - the ones that best represent who they are.
Copy the EXACT tweet text. Include tweets that are:
- Spicy, controversial, or attention-grabbing
- Deeply revealing of their worldview
- Representative of their main obsessions
- Particularly viral or engagement-heavy

FORMAT YOUR RESPONSE EXACTLY LIKE THIS:

## THE JUICER
[Your punchy paragraph here - no bullet points, just prose]

## KEY THEMES
- [theme 1]
- [theme 2]
(3-5 themes)

## HIGHLIGHTED TWEETS
1. "[EXACT tweet text copied verbatim]" - [why it's notable, 5-10 words]
2. "[EXACT tweet text copied verbatim]" - [why it's notable]
... (15-20 tweets)

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
        tweets = []
        lines = analysis_text.split('\n')
        in_highlights = False
        
        for line in lines:
            line_stripped = line.strip()
            
            # Detect highlights section
            if 'HIGHLIGHTED TWEETS' in line.upper() or 'NOTABLE TWEETS' in line.upper():
                in_highlights = True
                continue
            
            # Stop at next section
            if in_highlights and line_stripped.startswith('##'):
                break
            
            # Extract numbered tweets
            if in_highlights and line_stripped:
                # Match patterns like: 1. "tweet" - reason  OR  1. tweet - reason
                import re
                match = re.match(r'^\d+[\.\)]\s*"?(.+?)"?\s*[-–—]\s*(.+)$', line_stripped)
                if match:
                    tweet_text = match.group(1).strip().strip('"')
                    reason = match.group(2).strip()
                    if len(tweet_text) > 10:  # Filter out too-short matches
                        tweets.append({
                            "text": tweet_text,
                            "reason": reason
                        })
                elif line_stripped.startswith(tuple('0123456789')):
                    # Simpler pattern - just numbered item
                    text = re.sub(r'^\d+[\.\)]\s*', '', line_stripped)
                    if len(text) > 20:
                        tweets.append({
                            "text": text,
                            "reason": ""
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
