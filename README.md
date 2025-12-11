# Nitter Tweet Analyzer

A Python web application that scrapes tweets via a self-hosted Nitter instance and analyzes them using Google Gemini AI.

## Features

- Scrapes tweets from any public Twitter/X user via Nitter
- Handles pagination to collect as many tweets as possible
- Rate-limit aware with configurable delays
- Analyzes tweet themes and content using Google Gemini
- Clean web interface for easy use

## Prerequisites

- Python 3.11+
- Docker and Docker Compose (for self-hosted Nitter)
- Google Gemini API key

## Quick Start

### 1. Start Nitter

```bash
docker-compose up -d
```

This starts:
- Nitter on `http://localhost:8080`
- Redis for caching

### 2. Configure Environment

Copy the example env file and add your Gemini API key:

```bash
cp env.example .env
```

Edit `.env`:
```
NITTER_URL=http://localhost:8080
GEMINI_API_KEY=your_actual_api_key_here
SCRAPE_DELAY_SECONDS=1.0
MAX_TWEETS=500
```

### 3. Install Dependencies

```bash
pip install -r requirements.txt
```

### 4. Run the Application

```bash
uvicorn app.main:app --reload
```

Open `http://localhost:8000` in your browser.

## Configuration

| Variable | Default | Description |
|----------|---------|-------------|
| `NITTER_URL` | `http://localhost:8080` | URL of your Nitter instance |
| `GEMINI_API_KEY` | (required) | Your Google Gemini API key |
| `SCRAPE_DELAY_SECONDS` | `1.0` | Delay between page fetches |
| `MAX_TWEETS` | `500` | Maximum tweets to scrape per user |

## API Endpoints

### `POST /api/analyze`

Scrape and analyze tweets from a user.

Request body:
```json
{
  "username": "elonmusk",
  "include_retweets": false,
  "include_replies": false,
  "max_tweets": 100,
  "custom_prompt": null
}
```

### `POST /api/scrape`

Scrape tweets without analysis (for testing).

### `GET /health`

Check application health and configuration status.

## Troubleshooting

### Nitter not working

Nitter depends on Twitter's backend and may require guest account tokens. Check the Nitter logs:

```bash
docker-compose logs nitter
```

### Rate limiting

If you're getting rate limited:
- Increase `SCRAPE_DELAY_SECONDS`
- Reduce `MAX_TWEETS`
- Wait before trying again

### Gemini errors

Ensure your API key is valid and has sufficient quota. The application uses `gemini-1.5-flash` by default.

## License

MIT




