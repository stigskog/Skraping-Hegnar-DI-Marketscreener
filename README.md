# Stox.no Signal Generator

Web app that scrapes Nordic financial news sources, classifies stock signals using AI, and generates formatted Excel reports.

## Features

- Scrapes **Finansavisen**, **Dagens Industri (DI.se)**, and **MarketScreener**
- AI classification with multiple providers: DeepSeek, OpenAI, Claude, Gemini
- Generates Excel files matching the Stox.no format (grouped by country, sorted by time and name)
- Manual classification mode - paste any raw text and extract signals
- Scheduled automatic runs
- Dark/light theme

## Deploy to Railway

1. Push this repo to GitHub
2. Connect the repo to Railway (GitHub sync)
3. Deploy - Railway will auto-detect the config

## Setup After Deploy

1. Login with default credentials: `admin` / `admin123`
2. Go to **Settings** and change your password
3. Add your AI API key (DeepSeek recommended - cheapest option)
4. Click **Run All Sources** on the Dashboard

## Local Development

```bash
pip install -r requirements.txt
python app.py
```

App runs at `http://localhost:5000`
