# SigmapipsAI Trading Bot

An advanced Telegram trading bot deployed on Railway for processing and distributing trading signals with real-time analysis.

## Live Bot
Bot is live on Telegram: [@SignapipsAI_bot](https://t.me/SignapipsAI_bot)

## Features

### 1. Telegram Service
- Fully automated signal distribution
- AI-powered signal formatting using GPT-4
- Personalized preferences per user
- Support for multiple markets:
  - Forex
  - Indices 
  - Commodities
  - Crypto
- Interactive buttons for analysis

### 2. Real-time Analysis
- 📊 Technical Analysis Charts
  - Multiple timeframes (1m to 1d)
  - Automatic chart generation
  - Cached for quick access
- 🤖 Market Sentiment Analysis
  - AI-powered sentiment analysis
  - Real-time news processing
  - Perplexity AI integration
- 📅 Economic Calendar
  - Important economic events
  - Impact level filtering
  - Currency-specific events

### 3. Caching & Performance
- Redis caching for:
  - Trading signals
  - Technical analysis charts
  - Market sentiment data
  - Economic calendar events
- Base64 encoding for binary data
- Cache TTL: 1 hour
- Optimal performance through caching

## Tech Stack

### Backend
- FastAPI (Python 3.11)
- python-telegram-bot v20
- Redis for caching
- Supabase (PostgreSQL) for data storage

### AI Services
- OpenAI GPT-4 API for signal formatting
- Perplexity AI for market sentiment
- Custom prompts for consistent output

### Deployment
- Hosted on Railway
- Automatic deployments
- Webhook integration
- Health checks
- Auto-scaling
- Redis persistence

## Setup & Installation

1. Clone the repository:
```bash
git clone https://github.com/yourusername/sigmapips-bot.git
cd sigmapips-bot
```

2. Create a .env file:
```env
# Telegram
TELEGRAM_BOT_TOKEN=your_bot_token

# Supabase
SUPABASE_URL=your_supabase_url 
SUPABASE_KEY=your_supabase_key

# Redis
REDIS_URL=your_redis_url

# OpenAI
OPENAI_API_KEY=your_openai_key

# Perplexity
PERPLEXITY_API_KEY=your_perplexity_key

# Railway
RAILWAY_PUBLIC_DOMAIN=your_railway_domain
```

3. Start locally with Docker:
```bash
docker-compose up -d
```

## Bot Commands

- `/start` - Start setting up trading preferences
- `/manage` - Manage existing preferences
- `/menu` - Show main menu
- `/help` - Show help information

## Database Schema

```sql
CREATE TABLE subscriber_preferences (
    id bigint PRIMARY KEY GENERATED ALWAYS AS IDENTITY,
    user_id bigint NOT NULL,
    market text NOT NULL,
    instrument text NOT NULL, 
    timeframe text NOT NULL,
    created_at timestamp with time zone DEFAULT timezone('utc'::text, now()),
    updated_at timestamp with time zone DEFAULT timezone('utc'::text, now()),
    is_active boolean DEFAULT true,
    UNIQUE(user_id, market, instrument, timeframe)
);
```

## API Endpoints

### Signal Endpoint
```http
POST /signal
{
    "symbol": "EURUSD",
    "action": "BUY/SELL",
    "price": "1.0850",
    "stopLoss": "1.0800",
    "takeProfit": "1.0900",
    "timeframe": "1h",
    "market": "forex"
}
```

### Webhook Endpoint
```http
POST /webhook
- Handles Telegram updates
```

### Health Check
```http
GET /health
- Returns service status
```

## Error Handling

- Extensive logging of all operations
- Automatic retry mechanisms for API calls
- Graceful degradation during service outages
- Fallback options for AI services

## Railway Deployment

The application runs on Railway with:
- Automatic deployments via GitHub
- Webhook integration for Telegram
- Redis persistence for caching
- Health checks for uptime monitoring
- Auto-scaling based on load
- Zero-downtime deployments

## Contributing

1. Fork the repository
2. Create a feature branch
3. Commit your changes
4. Push to the branch
5. Open a Pull Request

## License

MIT License

## Contact

For questions or suggestions, open an issue or submit a PR.
