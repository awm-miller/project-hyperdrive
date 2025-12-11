"""
Integration test script for Nitter Tweet Analyzer.

Run this after starting Nitter and configuring your .env file.

Usage:
    python test_app.py
"""

import asyncio
import os
import sys

from dotenv import load_dotenv

load_dotenv()


async def test_nitter_connection():
    """Test that we can connect to the Nitter instance."""
    from app.scraper import NitterScraper
    
    nitter_url = os.getenv("NITTER_URL", "http://localhost:8080")
    print(f"[TEST] Testing Nitter connection: {nitter_url}")
    
    try:
        import httpx
        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.get(nitter_url)
            if response.status_code == 200:
                print(f"[PASS] Nitter is accessible (status: {response.status_code})")
                return True
            else:
                print(f"[FAIL] Nitter returned status: {response.status_code}")
                return False
    except Exception as e:
        print(f"[FAIL] Could not connect to Nitter: {e}")
        return False


async def test_scraper():
    """Test the tweet scraper with a known public account."""
    from app.scraper import NitterScraper, compile_tweets_for_analysis
    
    print("\n[TEST] Testing tweet scraper...")
    
    # Use a well-known account that should have tweets
    test_username = "jack"  # Twitter's founder, should always exist
    
    async with NitterScraper(max_tweets=10, delay_seconds=0.5) as scraper:
        result = await scraper.scrape_user(test_username)
    
    if result.error:
        print(f"[WARN] Scraper returned error: {result.error}")
        if result.rate_limited:
            print("[INFO] Rate limited - this is expected if Nitter has issues")
        return False
    
    if result.total_scraped > 0:
        print(f"[PASS] Scraped {result.total_scraped} tweets from @{test_username}")
        
        # Test compilation
        compiled = compile_tweets_for_analysis(result, max_chars=1000)
        if compiled:
            print(f"[PASS] Compiled tweets ({len(compiled)} chars)")
            print(f"[INFO] Sample: {compiled[:200]}...")
        return True
    else:
        print(f"[FAIL] No tweets scraped from @{test_username}")
        return False


def test_gemini_connection():
    """Test that we can connect to Gemini API."""
    from app.analyzer import GeminiAnalyzer
    
    print("\n[TEST] Testing Gemini API connection...")
    
    api_key = os.getenv("GEMINI_API_KEY")
    if not api_key:
        print("[FAIL] GEMINI_API_KEY not set in environment")
        return False
    
    if len(api_key) < 10 or api_key == "your_gemini_api_key_here":
        print("[FAIL] GEMINI_API_KEY appears to be a placeholder")
        return False
    
    try:
        analyzer = GeminiAnalyzer(api_key=api_key)
        
        # Simple test prompt
        result = analyzer.analyze(
            compiled_tweets="Test tweet 1: Hello world\nTest tweet 2: Testing 123",
            username="test_user",
            tweet_count=2,
        )
        
        if result.error:
            print(f"[FAIL] Gemini returned error: {result.error}")
            return False
        
        if result.summary:
            print(f"[PASS] Gemini returned analysis ({len(result.summary)} chars)")
            print(f"[INFO] Sample: {result.summary[:200]}...")
            return True
        else:
            print("[FAIL] Gemini returned empty response")
            return False
            
    except Exception as e:
        print(f"[FAIL] Gemini test failed: {e}")
        return False


async def test_fastapi_app():
    """Test that the FastAPI app starts and responds."""
    from fastapi.testclient import TestClient
    from app.main import app
    
    print("\n[TEST] Testing FastAPI application...")
    
    try:
        with TestClient(app) as client:
            # Test health endpoint
            response = client.get("/health")
            if response.status_code == 200:
                data = response.json()
                print(f"[PASS] Health endpoint OK")
                print(f"[INFO] Nitter URL: {data.get('nitter_url')}")
                print(f"[INFO] Gemini configured: {data.get('gemini_configured')}")
            else:
                print(f"[FAIL] Health endpoint returned: {response.status_code}")
                return False
            
            # Test home page
            response = client.get("/")
            if response.status_code == 200:
                print(f"[PASS] Home page loads ({len(response.text)} bytes)")
            else:
                print(f"[FAIL] Home page returned: {response.status_code}")
                return False
            
        return True
        
    except Exception as e:
        print(f"[FAIL] FastAPI test failed: {e}")
        return False


async def main():
    """Run all integration tests."""
    print("=" * 60)
    print("Nitter Tweet Analyzer - Integration Tests")
    print("=" * 60)
    
    results = {}
    
    # Test 1: Nitter connection
    results["nitter"] = await test_nitter_connection()
    
    # Test 2: Scraper (only if Nitter is accessible)
    if results["nitter"]:
        results["scraper"] = await test_scraper()
    else:
        print("\n[SKIP] Skipping scraper test (Nitter not accessible)")
        results["scraper"] = None
    
    # Test 3: Gemini API
    results["gemini"] = test_gemini_connection()
    
    # Test 4: FastAPI app
    results["fastapi"] = await test_fastapi_app()
    
    # Summary
    print("\n" + "=" * 60)
    print("Test Summary")
    print("=" * 60)
    
    all_passed = True
    for test_name, passed in results.items():
        if passed is None:
            status = "SKIP"
        elif passed:
            status = "PASS"
        else:
            status = "FAIL"
            all_passed = False
        print(f"  {test_name}: {status}")
    
    print("\n" + "=" * 60)
    if all_passed:
        print("All tests passed! The application is ready to use.")
        print("\nTo start the app:")
        print("  uvicorn app.main:app --reload")
        print("\nThen open http://localhost:8000")
    else:
        print("Some tests failed. Please check the configuration.")
        print("\nMake sure:")
        print("  1. Docker is running and Nitter is started (docker-compose up -d)")
        print("  2. GEMINI_API_KEY is set in your .env file")
    print("=" * 60)
    
    return 0 if all_passed else 1


if __name__ == "__main__":
    exit_code = asyncio.run(main())
    sys.exit(exit_code)




