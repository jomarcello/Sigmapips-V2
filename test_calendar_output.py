import re
from datetime import datetime

def format_calendar_events():
    """Simulation of the calendar output"""
    output = []
    # Using HTML formatting for the title and emoji
    output.append("<b>📅 Economic Calendar</b>")
    
    # Get the current date in different formats
    today = datetime.now()
    today_formatted = today.strftime("%B %d, %Y")
    
    output.append(f"\nDate: {today_formatted}")
    output.append("\nImpact: 🔴 High   🟠 Medium   🟢 Low")
    output.append("")
    
    # Sample currency groups and events
    currency_groups = {
        "JPY": [
            {"time": "00:30", "impact": "high", "title": "Capacity Utilization (MoM) (Feb)"},
            {"time": "00:30", "impact": "medium", "title": "Industrial Production (MoM) (Feb)"}
        ],
        "USD": [
            {"time": "07:00", "impact": "medium", "title": "OPEC Monthly Report"},
            {"time": "11:00", "impact": "medium", "title": "NY Fed 1-Year Consumer Inflation Expectations (Mar)"},
            {"time": "11:30", "impact": "low", "title": "3-Month Bill Auction"},
            {"time": "11:30", "impact": "low", "title": "6-Month Bill Auction"}
        ],
        "AUD": [
            {"time": "21:30", "impact": "medium", "title": "RBA Meeting Minutes"}
        ]
    }
    
    # Flag mapping
    flags = {
        "USD": "🇺🇸",
        "EUR": "🇪🇺", 
        "GBP": "🇬🇧",
        "JPY": "🇯🇵",
        "CHF": "🇨🇭",
        "CAD": "🇨🇦",
        "AUD": "🇦🇺",
        "NZD": "🇳🇿"
    }
    
    # Add events to the message, grouped by currency
    for currency_code, events in currency_groups.items():
        # Show currency header with flag
        flag = flags.get(currency_code, "")
        output.append(f"{flag} {currency_code}")
        
        # Show events for this currency
        for event in events:
            # Map impact to emoji
            impact_emoji = "🟢"  # Default Low
            if event["impact"] == "high":
                impact_emoji = "🔴"
            elif event["impact"] == "medium":
                impact_emoji = "🟠"
            
            # Simplify event title by removing date references
            title = event["title"]
            # Remove quarter indicators (Q1), (Q2) etc.
            title = re.sub(r'\s*\(Q[1-4]\)\s*', ' ', title)
            # Remove month/year indicators like (Mar), (Apr), etc.
            title = re.sub(r'\s*\([A-Za-z]{3}\)\s*', ' ', title)
            # Remove change period indicators like (MoM), (YoY), (QoQ)
            title = re.sub(r'\s*\((?:MoM|YoY|QoQ)\)\s*', ' ', title)
            # Remove date patterns like (Jan/2024)
            title = re.sub(r'\s*\([A-Za-z]{3}/\d{4}\)\s*', ' ', title)
            # Remove trailing spaces
            title = title.strip()
            
            output.append(f"{event['time']} - {impact_emoji} {title}")
        
        # Empty line between currencies
        output.append("")
    
    # Only add the note once
    output.append("Note: Only showing events scheduled for today.")
    
    return "\n".join(output)

if __name__ == "__main__":
    calendar_output = format_calendar_events()
    print(calendar_output)
    print("\n" + "=" * 50 + "\n")
    print("HTML tags will be rendered in Telegram, this is how it will look like:")
    print(calendar_output.replace("<b>", "").replace("</b>", "")) 