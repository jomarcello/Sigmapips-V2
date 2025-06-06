"""
Telegram bot conversation states
"""

# Conversation states
MENU = 0
ANALYSIS = 1
SIGNALS = 2
CHOOSE_ANALYSIS = 3
CHOOSE_SIGNALS = 4
CHOOSE_MARKET = 5
CHOOSE_INSTRUMENT = 6
CHOOSE_STYLE = 7
SHOW_RESULT = 8
CHOOSE_TIMEFRAME = 9
SIGNAL_DETAILS = 10
SIGNAL = 11
SUBSCRIBE = 12
BACK_TO_MENU = 13

# Callback data constants
CALLBACK_ANALYSIS_TECHNICAL = "analysis_technical"
CALLBACK_ANALYSIS_SENTIMENT = "analysis_sentiment"
CALLBACK_ANALYSIS_CALENDAR = "analysis_calendar"
CALLBACK_BACK_MENU = "back_menu"
CALLBACK_BACK_ANALYSIS = "back_analysis"
CALLBACK_BACK_MARKET = "back_market"
CALLBACK_BACK_INSTRUMENT = "back_instrument"
CALLBACK_BACK_SIGNALS = "back_signals"
CALLBACK_SIGNALS_ADD = "signals_add"
CALLBACK_SIGNALS_MANAGE = "signals_manage"
CALLBACK_MENU_ANALYSE = "menu_analyse"
CALLBACK_MENU_SIGNALS = "menu_signals"
CALLBACK_MENU_ANALYSIS_TECHNICAL = "menu_analysis_technical"
CALLBACK_MENU_ANALYSIS_SENTIMENT = "menu_analysis_sentiment"
CALLBACK_MENU_ANALYSIS_CALENDAR = "menu_analysis_calendar"
CALLBACK_MENU_BACK_MENU = "menu_back_menu"
CALLBACK_MENU_BACK_ANALYSIS = "menu_back_analysis"
CALLBACK_MENU_BACK_MARKET = "menu_back_market"
CALLBACK_MENU_BACK_INSTRUMENT = "menu_back_instrument"
CALLBACK_SIGNAL_TECHNICAL = "signal_technical"
CALLBACK_SIGNAL_SENTIMENT = "signal_sentiment"
CALLBACK_SIGNAL_CALENDAR = "signal_calendar"
CALLBACK_SIGNAL_BACK_ANALYSIS = "signal_back_analysis"
CALLBACK_SIGNAL_BACK_TO_SIGNAL = "back_to_signal"
CALLBACK_SIGNAL_BACK_TO_SIGNAL_ANALYSIS = "back_to_signal_analysis"
CALLBACK_SIGNAL_BACK_SIGNALS = "back_signals"
CALLBACK_SIGNAL_SIGNALS_ADD = "signal_signals_add"
CALLBACK_SIGNAL_SIGNALS_MANAGE = "signal_signals_manage"

# Market types
MARKET_FOREX = "forex"
MARKET_CRYPTO = "crypto"
MARKET_COMMODITIES = "commodities"
MARKET_INDICES = "indices"

# Timeframes
TIMEFRAME_1M = "1m"
TIMEFRAME_5M = "5m"
TIMEFRAME_15M = "15m"
TIMEFRAME_30M = "30m"
TIMEFRAME_1H = "1h"
TIMEFRAME_4H = "4h"
TIMEFRAME_1D = "1d"

# Menu states
SHOW_PREFERENCES = 8
MANAGE_PREFERENCES = 9
DELETE_PREFERENCE = 10
EDIT_PREFERENCE = 11

# Signal states
SIGNAL_MENU = 20
SIGNAL_CONFIRM = 21
SIGNAL_ANALYSIS = 22
SIGNAL_SETTINGS = 23

# Analysis states
ANALYSIS_MENU = 30
TECHNICAL_ANALYSIS = 31
SENTIMENT_ANALYSIS = 32
CALENDAR_ANALYSIS = 33

# Settings states
SETTINGS_MENU = 40
NOTIFICATION_SETTINGS = 41
RISK_SETTINGS = 42
STYLE_SETTINGS = 43

# Error states
ERROR = 99 
