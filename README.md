# SigmaPips Trading Bot

Een geavanceerde Telegram trading bot gedeployed op Railway voor het verwerken en distribueren van trading signalen met real-time analyses.

## Live Demo
Bot is live op Telegram: [@SigmapipsAITest_bot](https://t.me/Signapipstest4_bot)

## Features

### 1. Telegram Service
- Volledig geautomatiseerde signaal distributie
- AI-powered signal formatting met GPT-4
- Gepersonaliseerde voorkeuren per gebruiker
- Support voor meerdere markten:
  - Forex
  - Indices 
  - Commodities
  - Crypto
- Interactieve knoppen voor analyses

### 2. Real-time Analyses
- 📊 Technische Analyse Charts
  - Multiple timeframes (1m tot 1d)
  - Automatische chart generatie
  - Cached voor snelle toegang
- 🤖 Market Sentiment Analysis
  - AI-powered sentiment analyse
  - Real-time nieuws verwerking
  - Perplexity AI integratie
- 📅 Economic Calendar
  - Belangrijke economische events
  - Impact level filtering
  - Currency-specifieke events

### 3. Caching & Performance
- Redis caching voor:
  - Trading signalen
  - Technische analyse charts
  - Market sentiment data
  - Economic calendar events
- Base64 encoding voor binary data
- Cache TTL: 1 uur
- Optimale performance door caching

## Tech Stack

### Backend
- FastAPI (Python 3.11)
- python-telegram-bot v20
- Redis voor caching
- Supabase (PostgreSQL) voor data opslag

### AI Services
- OpenAI GPT-4 API voor signal formatting
- Perplexity AI voor market sentiment
- Custom prompts voor consistente output

### Deployment
- Gehost op Railway
- Automatische deployments
- Webhook integratie
- Health checks
- Auto-scaling
- Redis persistence

## Setup & Installation

1. Clone de repository:
```bash
git clone https://github.com/yourusername/sigmapips-bot.git
cd sigmapips-bot
```

2. Maak een .env file:
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

3. Start lokaal met Docker:
```bash
docker-compose up -d
```

## Bot Commands

- `/start` - Begin met instellen trading voorkeuren
- `/manage` - Beheer bestaande voorkeuren 
- `/menu` - Toon hoofdmenu
- `/help` - Toon help informatie

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

- Uitgebreide logging van alle operaties
- Automatische retry mechanismen voor API calls
- Graceful degradation bij service uitval
- Fallback opties voor AI services

## Deployment op Railway

De applicatie draait op Railway met:
- Automatische deployments via GitHub
- Webhook integratie voor Telegram
- Redis persistence voor caching
- Health checks voor uptime monitoring
- Auto-scaling based on load
- Zero-downtime deployments

## Contributing

1. Fork de repository
2. Maak een feature branch
3. Commit je wijzigingen
4. Push naar de branch
5. Open een Pull Request

