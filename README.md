# TradingView Signal Bot Services

A collection of microservices for processing and distributing trading signals via Telegram.

## Services

### 1. Telegram Service
- Handles all Telegram bot interactions
- Manages subscriber preferences
- Distributes signals to subscribers
- Provides Technical Analysis, Market Sentiment and Economic Calendar data

### 2. News AI Service
- Analyzes market sentiment using AI
- Processes news and market data
- Provides sentiment analysis for trading pairs

### 3. Chart Service
- Generates technical analysis charts
- Supports multiple timeframes
- Provides chart images for Telegram messages

### 4. Calendar Service
- Tracks economic events and releases
- Provides real-time calendar updates
- Helps traders stay informed about market-moving events
- Supports filtering by impact level and currency

## Setup & Installation

1. Clone the repository
2. Copy `.env.example` to `.env` and fill in your credentials
3. Run `docker-compose up -d` to start all services

## Environment Variables

```env
# Telegram Bot
TELEGRAM_BOT_TOKEN=your_bot_token
TELEGRAM_CHAT_ID=your_chat_id

# Supabase
SUPABASE_URL=your_supabase_url
SUPABASE_KEY=your_supabase_key

# Redis
REDIS_HOST=redis
REDIS_PORT=6379
```

## API Endpoints

### Telegram Service (Port 5000)
- `POST /signal` - Send a new signal
- `GET /health` - Health check

### News AI Service (Port 5001)
- `POST /analyze` - Analyze market sentiment

### Chart Service (Port 5002)
- `POST /chart/bytes` - Generate chart image

### Calendar Service (Port 5003)
- `GET /calendar` - Get economic calendar events
- `GET /calendar/impact/{level}` - Filter events by impact level
- `GET /calendar/currency/{code}` - Filter events by currency

## Database Schema

### Subscriber Preferences
```sql
CREATE TABLE subscriber_preferences (
    id bigint PRIMARY KEY GENERATED ALWAYS AS IDENTITY,
    user_id bigint NOT NULL,
    market text NOT NULL,
    instrument text NOT NULL,
    timeframe text NOT NULL,
    created_at timestamp with time zone DEFAULT timezone('utc'::text, now()),
    updated_at timestamp with time zone DEFAULT timezone('utc'::text, now()),
    UNIQUE(user_id, market, instrument, timeframe)
);
```

## Bot Commands
- `/start` - Start subscription process
- `/preferences` - Manage your signal preferences
