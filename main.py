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

# Setup basic logging
logging.basicConfig(level=logging.DEBUG)

# Set up Google Maps API client
gmaps = googlemaps.Client(key='')  # Add your Google Maps API key here

# Create Flask app and SocketIO instance
app = Flask(__name__)
# Generate a new secret key
app.secret_key = secrets.token_hex(16)
socketio = SocketIO(app)

def format_output(text):
    """แปลง Markdown เป็น HTML โดยให้ลิงก์สามารถคลิกได้ และแสดงรูปถ้าเป็น URL ของรูป"""
    
    # แปลง **bold text** เป็น <strong>
    text = re.sub(r'\*\*(.*?)\*\*', r'<strong>\1</strong>', text)

    # ตรวจจับ URL ของรูปภาพปกติ (เช่น .jpg, .png, .gif)
    image_pattern = r'(https?://[^\s]+(?:\.jpg|\.jpeg|\.png|\.gif|\.bmp|\.webp))'
    text = re.sub(image_pattern, r'<img src="\1" alt="Image" style="max-width:100%; height:auto;">', text)

    # ตรวจจับ Google Drive Direct Link และแปลงเป็นรูปภาพ (ใช้ export=view)
    drive_pattern = r'https://drive\.google\.com/uc\?id=([a-zA-Z0-9_-]+)'
    text = re.sub(drive_pattern, r'<img src="https://drive.google.com/uc?export=view&id=\1" alt="Google Drive Image" style="max-width:100%; height:auto;">', text)

    # ตรวจจับ Google Drive แบบ `/file/d/FILE_ID/view` และแปลงเป็น `<img>`
    drive_file_pattern = r'https://drive\.google\.com/file/d/([a-zA-Z0-9_-]+)/view'
    text = re.sub(drive_file_pattern, r'<img src="https://drive.google.com/uc?export=view&id=\1" alt="Google Drive Image" style="max-width:100%; height:auto;">', text)

    # แปลง URL ที่ไม่ใช่รูปภาพเป็น <a href>
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
        # Initialize OpenAI LLM and output parser
        llama_model = Ollama(model="llama3:latest")
        output_formatter = StrOutputParser()

        # Create chain
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

        # Get response from chatbot
        try:
            response = chatbot_pipeline.invoke(query_input)
        except Exception as e:
            logging.error(f"Chatbot error: {e}")
            response = "Sorry, I couldn't process your request. Please try again later."

        # Check if the query is related to choosing a trip type (interactive choice)
        if "trip type" in query_input.lower() or "plan a trip" in query_input.lower():
            # Present interactive choices
            response = create_trip_type_buttons()

        # Check if the query contains a place or location
        location = None
        if "where is" in query_input.lower() or "location of" in query_input.lower():
            # Extract location name from the query
            location = query_input.lower().replace("where is", "").replace("location of", "").strip()

        if location:
            # Get place details using the Google Maps API
            try:
                geocode_result = gmaps.geocode(location)
                if not geocode_result:
                    response = f"Sorry, I couldn't find information for {location}. Please try again."
                    emit('receive_message', {'message': response, 'timestamp': datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')})
                    return

                # Get the first result from geocode and extract location data
                place_name = geocode_result[0]['formatted_address']
                latitude = geocode_result[0]['geometry']['location']['lat']
                longitude = geocode_result[0]['geometry']['location']['lng']

                # Generate Google Maps URL for the location
                map_url = f"https://www.google.com/maps?q={latitude},{longitude}"

                # Include the map link in the response
                response += f"\n\nHere is the map link for {place_name}: <a href='{map_url}' target='_blank'>{place_name}</a>"
            except googlemaps.exceptions.ApiError as e:
                logging.error(f"Google Maps API error: {e}")
                response = "Sorry, I couldn't fetch location data at the moment. Please try again later."

        # Append chatbot response to history
        chat_history.append(("system", response, datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')))

        # Format output
        output = format_output(response)
        
        # Update session history
        session['history'] = chat_history
        session.modified = True  # Mark session as modified

        # Emit response back to client
        emit('receive_message', {
            'message': output,
            'timestamp': datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        }, json=True)

    except Exception as e:
        logging.error(f"Error during chatbot invocation: {e}")
        emit('receive_message', {'message': f"Sorry, an error occurred while processing your request: {e}", 'timestamp': datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')})

if __name__ == '__main__':
    socketio.run(app, debug=True)
