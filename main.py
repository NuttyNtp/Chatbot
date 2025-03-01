import openai
import googlemaps
from langchain_community.llms import Ollama
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.output_parsers import StrOutputParser
from flask import Flask, render_template, session
from flask_socketio import SocketIO, emit
import logging
import re
import datetime
import secrets
import mysql.connector
import asyncio
import aiohttp

# Setup basic logging
logging.basicConfig(level=logging.DEBUG)

# Set up Google Maps API client
gmaps = googlemaps.Client(key='AIzaSyDv_OEg50nhbpvW-EtNy3ze-dqsG4tPEEI')  # Add your Google Maps API key here

# Create Flask app and SocketIO instance
app = Flask(__name__)
# Generate a new secret key
app.secret_key = secrets.token_hex(16)
socketio = SocketIO(app, async_mode='eventlet')  # Use eventlet for async mode

def format_output(text):
    """แปลง Markdown เป็น HTML โดยให้ลิงก์สามารถคลิกได้ และแสดงรูปถ้าเป็น URL ของรูป"""
    text = re.sub(r'\*\*(.*?)\*\*', r'<strong>\1</strong>', text)
    image_pattern = r'(https?://[^\s]+(?:\.jpg|\.jpeg|\.png|\.gif|\.bmp|\.webp))'
    text = re.sub(image_pattern, r'<img src="\1" alt="Image" style="max-width:100%; height:auto;">', text)
    drive_pattern = r'https://drive\.google\.com/uc\?id=([a-zA-Z0-9_-]+)'
    text = re.sub(drive_pattern, r'<img src="https://drive.google.com/uc?export=view&id=\1" alt="Google Drive Image" style="max-width:100%; height:auto;">', text)
    drive_file_pattern = r'https://drive\.google\.com/file/d/([a-zA-Z0-9_-]+)/view'
    text = re.sub(drive_file_pattern, r'<img src="https://drive.google.com/uc?export=view&id=\1" alt="Google Drive Image" style="max-width:100%; height:auto;">', text)
    text = re.sub(r'(?<!<img src=")(https?://[^\s]+)(?!")', r'<a href="\1" target="_blank">\1</a>', text)
    return text

# Database connection function
def connect_db():
    return mysql.connector.connect(
        host="localhost",
        user="root",  # Your MySQL username
        password="",  # Your MySQL password (leave blank if default)
        database="travel_chatbot",
        port=3308  # Use the correct port here
    )

# Query the database for image metadata
def get_image_metadata(place_name):
    db = connect_db()
    cursor = db.cursor(dictionary=True)
    cursor.execute("SELECT * FROM images WHERE place_name = %s", (place_name,))
    result = cursor.fetchone()
    db.close()
    return result

# Define chatbot initialization
def initialise_llama3():
    try:
        llama_model = Ollama(model="llama3:latest")
        output_formatter = StrOutputParser()
        chatbot_pipeline = llama_model | output_formatter
        return chatbot_pipeline
    except Exception as e:
        logging.error(f"Failed to initialize chatbot: {e}")
        raise

# Initialize chatbot
chatbot_pipeline = initialise_llama3()

@app.route('/')
def main():
    return render_template('home.html')

@app.route('/index')
def chat_page():
    return render_template('index.html')

def create_trip_type_buttons():
    """Create buttons for selecting a trip type."""
    return {
        'message': 'Please select the type of trip you are interested in:',
        'buttons': [
            {'text': 'Adventure Trip', 'value': 'adventure'},
            {'text': 'Beach Vacation', 'value': 'beach'},
            {'text': 'Cultural Tour', 'value': 'cultural'},
            {'text': 'Nature Escape', 'value': 'nature'},
        ]
    }

# Asynchronous function to get location info from Google Maps API
async def fetch_location_info(location):
    async with aiohttp.ClientSession() as session:
        async with session.get(f'https://maps.googleapis.com/maps/api/geocode/json?address={location}&key=YOUR_GOOGLE_MAPS_API_KEY') as response:
            return await response.json()

# Asynchronous function to get chatbot response
async def fetch_chatbot_response(query_input):
    try:
        response = await chatbot_pipeline.invoke(query_input)
        return response
    except Exception as e:
        logging.error(f"Chatbot error: {e}")
        return "Sorry, I couldn't process your request. Please try again later."

@socketio.on('send_message')
def handle_send_message(data):
    query_input = data.get('message', '').strip()
    if not query_input:
        emit('receive_message', {'message': "Please provide a message to continue.", 'timestamp': datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')})
        return

    chat_history = session.get('history', [])
    try:
        # Append user query to history
        chat_history.append(("user", query_input, datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')))
        chat_messages = [(role, message) for role, message, _ in chat_history]  # Remove timestamp
        chat_messages.append(("system", "You are a travel assistant specializing in Thailand. Only answer questions related to travel in Thailand. If the question is unrelated, politely decline."))

        create_prompt = ChatPromptTemplate.from_messages(chat_messages)

        # Asynchronous fetch for both chatbot response and location info
        async def handle_query():
            location = None
            if "where is" in query_input.lower() or "location of" in query_input.lower():
                location = query_input.lower().replace("where is", "").replace("location of", "").strip()

            # Fetch both chatbot and location info concurrently
            chatbot_response = await fetch_chatbot_response(query_input)

            if location:
                location_info = await fetch_location_info(location)
                if not location_info.get('results'):
                    chatbot_response = f"Sorry, I couldn't find information for {location}. Please try again."
                else:
                    place_name = location_info['results'][0]['formatted_address']
                    latitude = location_info['results'][0]['geometry']['location']['lat']
                    longitude = location_info['results'][0]['geometry']['location']['lng']
                    map_url = f"https://www.google.com/maps?q={latitude},{longitude}"
                    chatbot_response += f"\n\nHere is the map link for {place_name}: <a href='{map_url}' target='_blank'>{place_name}</a>"

            # Format output
            output = format_output(chatbot_response)

            # Emit response back to client
            emit('receive_message', {'message': output, 'timestamp': datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}, json=True)

        # Run asynchronous query handler
        asyncio.run(handle_query())

    except Exception as e:
        logging.error(f"Error during chatbot invocation: {e}")
        emit('receive_message', {'message': f"Sorry, an error occurred while processing your request: {e}", 'timestamp': datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')})

if __name__ == '__main__':
    socketio.run(app, debug=True)
