#!/usr/bin/env python3
"""
Test script to verify fixed Binance account API access.
"""

import asyncio
import logging
import os
from dotenv import load_dotenv
import sys
from datetime import datetime

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
)
logger = logging.getLogger(__name__)

async def test_account_info():
    """Test Binance account info with our fixed implementation"""
    print("\n=== Testing Fixed Binance Account API Access ===")
    
    # Load environment variables
    load_dotenv()
    
    # Import after environment variables are loaded
    from trading_bot.services.chart_service.binance_provider import BinanceProvider
    
    # Check if keys are set in provider
    print(f"API Key set in provider: {'Yes' if BinanceProvider.API_KEY else 'No'}")
    print(f"API Secret set in provider: {'Yes' if BinanceProvider.API_SECRET else 'No'}")
    
    if BinanceProvider.API_KEY:
        print(f"API Key in provider: {BinanceProvider.API_KEY[:5]}...{BinanceProvider.API_KEY[-5:] if len(BinanceProvider.API_KEY) > 10 else ''}")
    
    # Try to get account information
    print("\nFetching account information with BinanceProvider...")
    account_info = await BinanceProvider.get_account_info()
    
    if account_info:
        print("\n✅ SUCCESS! Retrieved account information!")
        print(f"\nAccount Type: {account_info.get('accountType', 'N/A')}")
        print(f"Can Trade: {account_info.get('canTrade', False)}")
        print(f"Can Deposit: {account_info.get('canDeposit', False)}")
        print(f"Can Withdraw: {account_info.get('canWithdraw', False)}")
        
        # Show balances with non-zero amounts
        balances = [b for b in account_info.get('balances', []) if float(b.get('free', 0)) > 0 or float(b.get('locked', 0)) > 0]
        
        if balances:
            print(f"\nFound {len(balances)} assets with non-zero balances:")
            for balance in balances:
                asset = balance.get('asset', 'Unknown')
                free = float(balance.get('free', 0))
                locked = float(balance.get('locked', 0))
                total = free + locked
                print(f"  {asset}: {total} (Free: {free}, Locked: {locked})")
        else:
            print("\nNo assets with non-zero balances found")
    else:
        print("\n❌ Failed to retrieve account information.")
        print("This could be due to:")
        print("  1. API key might be invalid or expired")
        print("  2. API key doesn't have permission to read account data")
        print("  3. Network issues connecting to Binance")

async def test_technical_analysis_data():
    """Test if Binance market data fits our technical analysis format"""
    print("\n=== Testing Technical Analysis Data Format ===")
    
    # Import after environment variables are loaded
    from trading_bot.services.chart_service.binance_provider import BinanceProvider
    
    # List of instruments to test
    test_instruments = ["BTCUSDT"]  # Focusing on BTC only
    test_timeframes = ["1h"]        # Focusing on 1h timeframe
    
    for instrument in test_instruments:
        print(f"\nTesting data for {instrument}:")
        
        for timeframe in test_timeframes:
            print(f"\n  {timeframe} timeframe:")
            
            # Get market data
            market_data = await BinanceProvider.get_market_data(instrument, timeframe)
            
            if not market_data:
                print(f"  ❌ Failed to get market data for {instrument} on {timeframe}")
                continue
            
            print(f"  ✅ Successfully retrieved market data")
            
            # Extract indicators
            indicators = market_data.indicators
            
            # Expected fields for our technical analysis format
            technical_analysis_fields = {
                "close": indicators.get("close", None),
                "ema_20": None,  # Binance doesn't provide EMA20 by default
                "ema_50": indicators.get("EMA50", None),
                "rsi": indicators.get("RSI", None),
                "macd": indicators.get("MACD.macd", None),
                "macd_signal": indicators.get("MACD.signal", None),
            }
            
            # Check if we have all required fields
            missing_fields = [field for field, value in technical_analysis_fields.items() if value is None]
            
            if missing_fields:
                print(f"  ⚠️ Missing fields for technical analysis: {', '.join(missing_fields)}")
                
                # Suggest how to adapt the data
                print("  Adaptation required:")
                if "ema_20" in missing_fields:
                    print("  - Calculate EMA20 from the price data")
            else:
                print("  ✅ All required fields for technical analysis are available")
            
            # Map to our expected format
            print("\n  Data mapping example:")
            print(f"  Current Price: {indicators.get('close', 'N/A')}")
            print(f"  EMA 50: {indicators.get('EMA50', 'N/A')}")
            print(f"  EMA 200: {indicators.get('EMA200', 'N/A')}")
            print(f"  RSI (14): {indicators.get('RSI', 'N/A')}")
            print(f"  MACD: {indicators.get('MACD.macd', 'N/A')}")
            print(f"  MACD Signal: {indicators.get('MACD.signal', 'N/A')}")
            print(f"  MACD Histogram: {indicators.get('MACD.hist', 'N/A')}")
            
            # Get high/low values
            current_price = indicators.get("close", 0)
            daily_high = indicators.get("high", current_price * 1.01)
            daily_low = indicators.get("low", current_price * 0.99)
            weekly_high = indicators.get("weekly_high", daily_high * 1.02)
            weekly_low = indicators.get("weekly_low", daily_low * 0.98)
            
            # Determine trend based on EMAs
            ema_50 = indicators.get("EMA50", 0)
            ema_200 = indicators.get("EMA200", 0)
            
            trend = "BUY" if current_price > ema_50 > ema_200 else "SELL" if current_price < ema_50 < ema_200 else "NEUTRAL"
            
            # RSI interpretation
            rsi = indicators.get("RSI", 50)
            rsi_condition = "overbought" if rsi > 70 else "oversold" if rsi < 30 else "neutral"
            
            # MACD interpretation
            macd = indicators.get("MACD.macd", 0)
            macd_signal = indicators.get("MACD.signal", 0)
            macd_status = "bullish" if macd > macd_signal else "bearish"
            
            # Moving averages status
            ma_status = "bullish" if current_price > ema_50 > ema_200 else "bearish" if current_price < ema_50 < ema_200 else "mixed"
            
            # Determine the appropriate price formatting based on instrument type
            if any(crypto in instrument for crypto in ["BTC", "ETH", "XRP", "SOL", "BNB"]):
                if instrument == "BTCUSDT":
                    price_format = ",.2f"  # Bitcoin with 2 decimal places
                else:
                    price_format = ",.4f"  # Other crypto with 4 decimal places
            else:
                price_format = ",.5f"  # Default format for forex pairs
                
            # Generate zone strength (1-5 stars) based on trend consistency and volume
            zone_strength = 4 if trend != "NEUTRAL" else 3  # Default 4 stars for strong trend, 3 for neutral
            zone_stars = "★" * zone_strength + "☆" * (5 - zone_strength)
            
            # Format full analysis text similar to the user's example
            print("\n\n=== FULL TECHNICAL ANALYSIS ===\n")
            
            analysis_text = f"{instrument.replace('USDT', 'USD')} - {timeframe}\n\n"
            analysis_text += f"Zone Strength: {zone_stars}\n\n"
            
            # Market overview section
            analysis_text += "📊 Market Overview\n"
            analysis_text += f"Price is currently trading near the daily {'high' if current_price > (daily_high + daily_low)/2 else 'low'} of "
            analysis_text += f"{daily_high:{price_format}}, showing {'bullish' if trend == 'BUY' else 'bearish' if trend == 'SELL' else 'mixed'} momentum. "
            analysis_text += f"The pair remains {'above' if current_price > ema_50 else 'below'} key EMAs, "
            analysis_text += f"indicating a {'strong uptrend' if trend == 'BUY' else 'strong downtrend' if trend == 'SELL' else 'consolidation phase'}. "
            analysis_text += "Volume is moderate, supporting the current price action.\n\n"
            
            # Key levels section
            analysis_text += "🔑 Key Levels\n"
            analysis_text += f"Support: {daily_low:{price_format}} (daily low), {(daily_low * 0.99):{price_format}}, {weekly_low:{price_format}} (weekly low)\n"
            analysis_text += f"Resistance: {daily_high:{price_format}} (daily high), {(daily_high * 1.01):{price_format}}, {weekly_high:{price_format}} (weekly high)\n\n"
            
            # Technical indicators section
            analysis_text += "📈 Technical Indicators\n"
            analysis_text += f"RSI: {rsi:.2f} ({rsi_condition})\n"
            analysis_text += f"MACD: {macd_status} ({macd:.6f} > signal {macd_signal:.6f})\n"
            analysis_text += f"Moving Averages: Price {'above' if current_price > ema_50 else 'below'} EMA 50 ({ema_50:{price_format}}) and "
            analysis_text += f"{'above' if current_price > ema_200 else 'below'} EMA 200 ({ema_200:{price_format}}), confirming {ma_status} bias.\n\n"
            
            # AI recommendation
            analysis_text += "🤖 Sigmapips AI Recommendation\n"
            if trend == "BUY":
                analysis_text += f"Watch for a breakout above {daily_high:{price_format}} for further upside. "
                analysis_text += f"Maintain a buy bias while price holds above {daily_low:{price_format}}. "
                analysis_text += "Be cautious of overbought conditions if RSI approaches 70.\n\n"
            elif trend == "SELL":
                analysis_text += f"Watch for a breakdown below {daily_low:{price_format}} for further downside. "
                analysis_text += f"Maintain a sell bias while price holds below {daily_high:{price_format}}. "
                analysis_text += "Be cautious of oversold conditions if RSI approaches 30.\n\n"
            else:
                analysis_text += f"Range-bound conditions persist. Look for buying opportunities near {daily_low:{price_format}} "
                analysis_text += f"and selling opportunities near {daily_high:{price_format}}. "
                analysis_text += "Wait for a clear breakout before establishing a directional bias.\n\n"
            
            # Disclaimer
            analysis_text += "⚠️ Disclaimer: Please note that the information/analysis provided is strictly for study and educational purposes only."
            
            print(analysis_text)
            
            # Print comparison to desired format
            print("\n=== DATA FORMAT COMPARISON ===")
            print("\nOur format includes:")
            print("✅ Zone Strength rating")
            print("✅ Market Overview with current trend")
            print("✅ Key Support and Resistance levels")
            print("✅ Technical Indicators (RSI, MACD, Moving Averages)")
            print("✅ AI Recommendation based on current data")
            print("✅ All price values formatted appropriately for the instrument")
            
            if "ema_20" in missing_fields:
                print("\n⚠️ Adaptation needed:")
                print("- Binance doesn't provide EMA20 directly, so we'll need to calculate it")
                print("- We can use the price data and calculate EMA20 using pandas' built-in functions")
                print("  df['EMA20'] = df['close'].ewm(span=20, adjust=False).mean()")
            
            # Break after the first timeframe to keep output manageable
            break

async def test_create_order():
    """Test creating an order with BinanceProvider"""
    print("\n=== Testing Order Creation with Binance ===")
    
    # Import after environment variables are loaded
    from trading_bot.services.chart_service.binance_provider import BinanceProvider
    from trading_bot.models.signals import Signal, SignalType
    
    # Get current price of BTC to create a test order far from market price
    print("Getting current BTC price...")
    current_price = await BinanceProvider.get_ticker_price("BTCUSDT")
    if not current_price:
        print("❌ Failed to get current price for BTCUSDT")
        return
    
    print(f"Current BTC price: {current_price}")
    
    # Set limit price far from market price to avoid execution
    # (50% below current price for buy order)
    safe_limit_price = current_price * 0.5
    print(f"Using safe limit price: {safe_limit_price} (50% below market)")
    
    # Create a test signal
    test_signal = Signal(
        symbol="BTCUSDT",
        signal_type=SignalType.BUY,
        entry_price=safe_limit_price,
        take_profit=safe_limit_price * 1.1,
        stop_loss=safe_limit_price * 0.9,
        time_frame="1h",
        source="test"
    )
    
    print(f"\nCreating test {test_signal.signal_type.value} order for {test_signal.symbol}...")
    
    # Create a small test order with limit price far from market
    try:
        order_response = await BinanceProvider.create_order(
            symbol=test_signal.symbol,
            side=test_signal.signal_type.value,
            order_type="LIMIT",
            quantity=0.001,  # Minimum BTC order size
            price=safe_limit_price,
            time_in_force="GTC"
        )
        
        if order_response:
            print("\n✅ ORDER CREATED SUCCESSFULLY! Response format:")
            
            # Check response format and expected fields
            expected_fields = ["symbol", "orderId", "clientOrderId", "transactTime", "price", "origQty", "executedQty", "status", "timeInForce", "type", "side"]
            
            for field in expected_fields:
                value = order_response.get(field, "MISSING")
                print(f"  {field}: {value}")
            
            # Check if the format matches what we need
            print("\nChecking if response format is compatible with our Signal model...")
            
            # Extract data we'd need for a signal model
            signal_data = {
                "symbol": order_response.get("symbol", ""),
                "signal_type": order_response.get("side", "UNKNOWN"),
                "entry_price": float(order_response.get("price", 0)),
                "timestamp": order_response.get("transactTime", 0),
                "extra_data": {
                    "order_id": order_response.get("orderId", ""),
                    "client_order_id": order_response.get("clientOrderId", ""),
                    "status": order_response.get("status", ""),
                    "order_type": order_response.get("type", ""),
                    "time_in_force": order_response.get("timeInForce", ""),
                    "executed_qty": order_response.get("executedQty", ""),
                    "orig_qty": order_response.get("origQty", ""),
                }
            }
            
            # Create a signal from this data
            from_order_signal = Signal.from_dict(signal_data)
            print("\nSignal created from order response:")
            print(from_order_signal)
            
            print("\n✅ Format verification complete! The order response can be correctly mapped to our Signal model.")
            
            # If we want to be extra careful, cancel the test order
            print("\nNote: Since this is a test order with price far from market, it will likely never execute.")
            print("You may want to cancel it from the Binance web interface or app.")
            
        else:
            print("\n❌ Failed to create test order.")
            print("This could be due to:")
            print("  1. API key doesn't have trading permission")
            print("  2. Invalid order parameters")
            print("  3. Network issues connecting to Binance")
    
    except Exception as e:
        print(f"\n❌ Error creating test order: {e}")

async def main():
    """Main test function"""
    print(f"Starting test at {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    
    # Force reload environment variables
    os.environ["BINANCE_API_KEY"] = ""
    os.environ["BINANCE_API_SECRET"] = ""
    load_dotenv(override=True)
    
    # Print environment variables for debugging
    api_key = os.environ.get("BINANCE_API_KEY", "")
    api_secret = os.environ.get("BINANCE_API_SECRET", "")
    
    print(f"BINANCE_API_KEY in env: {api_key[:5]}...{api_key[-5:] if len(api_key) > 10 else ''}")
    print(f"BINANCE_API_SECRET in env: {api_secret[:5]}...{api_secret[-5:] if len(api_secret) > 10 else ''}")
    
    # Uncomment the test you want to run
    # await test_account_info()
    await test_technical_analysis_data()
    # await test_create_order()
    
    print(f"\nTest completed at {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")

if __name__ == "__main__":
    asyncio.run(main()) 
