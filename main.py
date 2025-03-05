from flask import Flask, render_template, session, request
from flask_socketio import SocketIO, emit
import logging
import re
import datetime
import secrets
import os
import urllib.parse
import requests
from langchain_community.llms import Ollama
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.output_parsers import StrOutputParser

# Setup basic logging
logging.basicConfig(level=logging.DEBUG)

# Create Flask app and SocketIO instance
app = Flask(__name__)
app.secret_key = secrets.token_hex(16)
socketio = SocketIO(app, cors_allowed_origins="*")

class BookingLinkGenerator:
    @staticmethod
    def get_hotel_booking_links(location):
        """Generate comprehensive hotel booking links for a specific location"""
        # URL encode the location
        encoded_location = urllib.parse.quote(location)
        
        # Define booking platforms with their URL templates
        booking_platforms = [
            {
                'name': 'Booking.com',
                'url': f'https://www.booking.com/searchresults.en-gb.html?ss={encoded_location}&no_rooms=1&group_adults=2'
            },
            {
                'name': 'Agoda',
                'url': f'https://www.agoda.com/en-gb/search?city={encoded_location}'
            },
            {
                'name': 'Expedia',
                'url': f'https://www.expedia.co.th/Hotels/Search?destination={encoded_location}'
            }
        ]
        
        # Generate markdown-style links
        links = [
            f"* [{platform['name']} - {location} Hotels]({platform['url']})"
            for platform in booking_platforms
        ]
        
        return "\n".join(links)

    @staticmethod
    def get_transportation_links(location):
        """Generate transportation booking links"""
        encoded_location = urllib.parse.quote(location)
        
        transport_platforms = [
            {
                'name': 'Flights',
                'url': f'https://www.skyscanner.com/transport/flights-to/{encoded_location}'
            },
            {
                'name': 'Buses',
                'url': f'https://www.12go.asia/en/thailand/{encoded_location}'
            },
            {
                'name': 'Trains',
                'url': f'https://www.thairailway.com/booking/{encoded_location}'
            }
        ]
        
        links = [
            f"* [{platform['name']} - {location}]({platform['url']})"
            for platform in transport_platforms
        ]
        
        return "\n".join(links)

# Initialize Ollama chatbot
ollama_model = Ollama(model="llama3:latest")
prompt_template = ChatPromptTemplate.from_template(
    "You are an expert Thailand travel assistant. Provide helpful, detailed, and engaging travel information.\n"
    "User's Request: {user_request}\n"
    "Chat History: {history}\n\n"
    "Guidelines:\n"
    "1. Always provide personalized, actionable travel advice.\n"
    "2. When mentioning destinations or services, include practical booking information.\n"
    "3. Create detailed, engaging responses that help travelers plan their trip.\n"
    "4. Be specific about locations, attractions, and travel logistics.\n"
    "Respond conversationally and helpfully."
)

output_parser = StrOutputParser()
chatbot_pipeline = prompt_template | ollama_model | output_parser

@socketio.on('send_message')
def handle_send_message(data):
    if not data or 'message' not in data:
        emit('receive_message', {'message': "Invalid request.", 'timestamp': datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')})
        return

    query_input = data['message']
    chat_history = session.get('history', [])
    
    try:
        # Prepare chat history
        history_text = "\n".join([f"{h[0]}: {h[1]}" for h in chat_history])
        
        # Generate response from Ollama
        ollama_response = chatbot_pipeline.invoke({
            "user_request": query_input,
            "history": history_text
        })
        
        # Extract location for booking links
        location_match = re.search(r'(Phuket|Bangkok|Chiang Mai|Krabi|Koh Samui)', ollama_response, re.IGNORECASE)
        location = location_match.group(1) if location_match else "Thailand"
        
        # Generate booking links
        hotel_links = BookingLinkGenerator.get_hotel_booking_links(location)
        transport_links = BookingLinkGenerator.get_transportation_links(location)
        
        # Append booking links to response
        full_response = ollama_response + "\n\n## Hotel Booking Options:\n" + hotel_links
        full_response += "\n\n## Transportation Booking Options:\n" + transport_links
        
        # Save and emit response
        chat_history.append(("user", query_input, datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')))
        chat_history.append(("system", full_response, datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')))
        session['history'] = chat_history
        session.modified = True
        
        emit('receive_message', {
            'message': full_response, 
            'timestamp': datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        })
    
    except Exception as e:
        logging.error(f"Error processing message: {e}")
        emit('receive_message', {
            'message': f"An error occurred: {str(e)}", 
            'timestamp': datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        })

# Rest of the Flask application setup remains the same
@app.route('/')
def main():
    return render_template('home.html')

@app.route('/index')
def chat_page():
    return render_template('index.html')

if __name__ == '__main__':
    socketio.run(app, debug=True)