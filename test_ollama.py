import os
import sys
import logging

# Setup logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s: %(message)s')

# Add the current directory to Python path
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

try:
    from main import OllamaChatbot
    
    # Test Ollama integration
    logging.info('Testing Ollama integration...')
    result = OllamaChatbot.get_travel_plan('Plan a 1-day trip to Bangkok')
    print('\nOllama Response:\n', result)
    
except Exception as e:
    logging.error(f'Error occurred: {str(e)}')
    raise