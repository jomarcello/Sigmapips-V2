import sys
import json
import time
from datetime import datetime

# Import the bot module
from bot import Bot
from sentiment import get_sentiment_analysis

def process_request(request_string):
    try:
        # Parse the request as JSON
        request = json.loads(request_string)
        
        # Extract the command
        command = request.get('command', '')
        
        if command == 'get_bot_response':
            # Extract user message
            user_message = request.get('user_message', '')
            
            # Create a bot instance and get response
            bot = Bot()
            response = bot.get_response(user_message)
            
            # Return the response
            return json.dumps({
                'status': 'success',
                'response': response
            })
            
        elif command == 'get_sentiment_analysis':
            # Extract instrument name
            instrument = request.get('instrument', '')
            
            if not instrument:
                return json.dumps({
                    'status': 'error',
                    'message': 'Missing instrument parameter'
                })
            
            # Get sentiment analysis with caching
            sentiment_analysis = get_sentiment_analysis(instrument)
            
            # Return the sentiment analysis
            return json.dumps({
                'status': 'success',
                'sentiment_analysis': sentiment_analysis
            })
            
        else:
            return json.dumps({
                'status': 'error',
                'message': 'Unknown command'
            })
    
    except Exception as e:
        return json.dumps({
            'status': 'error',
            'message': str(e)
        })

# Main entry point for the script
if __name__ == '__main__':
    # Check if a request was provided as an argument
    if len(sys.argv) > 1:
        request_string = sys.argv[1]
        response = process_request(request_string)
        print(response)
    else:
        print(json.dumps({
            'status': 'error',
            'message': 'No request provided'
        }))
