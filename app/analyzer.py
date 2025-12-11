"""
Gemini Tweet Analyzer Module

Sends compiled tweets to Google Gemini for thematic analysis.
"""

import os
from dataclasses import dataclass
from typing import Optional

import google.generativeai as genai
from dotenv import load_dotenv

load_dotenv()


@dataclass
class AnalysisResult:
    """Result of Gemini analysis."""
    summary: str
    themes: list[str]
    username: str
    tweet_count: int
    error: Optional[str] = None


class GeminiAnalyzer:
    """Analyzes tweets using Google Gemini API."""

    DEFAULT_PROMPT = """You are analyzing a collection of tweets from a Twitter/X user.

Please provide a comprehensive analysis including:

1. **Main Themes**: What are the primary topics and themes this user tweets about?

2. **Content Summary**: Provide a summary of the overall content and messaging.

3. **Tone & Style**: How would you describe their communication style?

4. **Key Interests**: What subjects or areas seem most important to this user?

5. **Notable Patterns**: Any recurring phrases, hashtags, or patterns in their tweeting behavior?

Please structure your response clearly with headers for each section.

Here are the tweets to analyze:

{tweets}
"""

    def __init__(self, api_key: Optional[str] = None, model: str = "gemini-2.0-flash"):
        """
        Initialize the Gemini analyzer.
        
        Args:
            api_key: Gemini API key (defaults to GEMINI_API_KEY env var)
            model: Gemini model to use
        """
        self.api_key = api_key or os.getenv("GEMINI_API_KEY")
        self.model_name = model
        self._model = None

        if not self.api_key:
            raise ValueError("GEMINI_API_KEY not provided or found in environment")

        genai.configure(api_key=self.api_key)

    def _get_model(self):
        """Get or create the Gemini model instance."""
        if self._model is None:
            self._model = genai.GenerativeModel(self.model_name)
        return self._model

    def analyze(
        self,
        compiled_tweets: str,
        username: str,
        tweet_count: int,
        custom_prompt: Optional[str] = None,
    ) -> AnalysisResult:
        """
        Analyze compiled tweets using Gemini.
        
        Args:
            compiled_tweets: Formatted string of tweets from compile_tweets_for_analysis
            username: Twitter username being analyzed
            tweet_count: Number of tweets included
            custom_prompt: Optional custom prompt (use {tweets} placeholder for tweets)
        
        Returns:
            AnalysisResult with analysis summary
        """
        if not compiled_tweets.strip():
            return AnalysisResult(
                summary="No tweets to analyze.",
                themes=[],
                username=username,
                tweet_count=0,
                error="No tweet content provided"
            )

        prompt_template = custom_prompt or self.DEFAULT_PROMPT
        
        # Ensure {tweets} placeholder exists
        if "{tweets}" not in prompt_template:
            prompt_template += "\n\nTweets:\n{tweets}"

        full_prompt = prompt_template.format(tweets=compiled_tweets)

        try:
            model = self._get_model()
            response = model.generate_content(full_prompt)
            
            # Extract the response text
            if response.text:
                summary = response.text
            else:
                # Handle blocked or empty responses
                if response.prompt_feedback:
                    return AnalysisResult(
                        summary="",
                        themes=[],
                        username=username,
                        tweet_count=tweet_count,
                        error=f"Content blocked: {response.prompt_feedback}"
                    )
                summary = "Unable to generate analysis."

            # Extract themes from the response (simple extraction)
            themes = self._extract_themes(summary)

            return AnalysisResult(
                summary=summary,
                themes=themes,
                username=username,
                tweet_count=tweet_count,
            )

        except Exception as e:
            error_msg = str(e)
            print(f"Gemini API error: {error_msg}")
            return AnalysisResult(
                summary="",
                themes=[],
                username=username,
                tweet_count=tweet_count,
                error=f"Gemini API error: {error_msg}"
            )

    def _extract_themes(self, analysis_text: str) -> list[str]:
        """
        Extract theme keywords from the analysis text.
        
        This is a simple extraction - looks for content under "Main Themes" section.
        """
        themes = []
        lines = analysis_text.split('\n')
        in_themes_section = False

        for line in lines:
            line_lower = line.lower().strip()
            
            # Detect themes section
            if 'main theme' in line_lower or 'primary topic' in line_lower:
                in_themes_section = True
                continue
            
            # Stop at next section
            if in_themes_section and line.startswith('**') and ':' in line:
                if 'theme' not in line_lower:
                    break
            
            # Extract bullet points as themes
            if in_themes_section:
                if line.strip().startswith(('-', '*', '•')):
                    theme = line.strip().lstrip('-*•').strip()
                    # Clean up the theme
                    if ':' in theme:
                        theme = theme.split(':')[0].strip()
                    if theme and len(theme) < 100:
                        themes.append(theme)

        return themes[:10]  # Limit to top 10 themes


async def analyze_tweets_async(
    compiled_tweets: str,
    username: str,
    tweet_count: int,
    api_key: Optional[str] = None,
    custom_prompt: Optional[str] = None,
) -> AnalysisResult:
    """
    Async wrapper for tweet analysis.
    
    Note: The underlying Gemini library is synchronous, so this just wraps
    the sync call for API consistency.
    """
    import asyncio
    
    analyzer = GeminiAnalyzer(api_key=api_key)
    
    # Run in executor to avoid blocking
    loop = asyncio.get_event_loop()
    result = await loop.run_in_executor(
        None,
        lambda: analyzer.analyze(compiled_tweets, username, tweet_count, custom_prompt)
    )
    
    return result


