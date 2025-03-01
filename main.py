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

# Google Maps API Key
GOOGLE_MAPS_API_KEY = os.getenv("GOOGLE_MAPS_API_KEY", "AIzaSyDv_OEg50nhbpvW-EtNy3ze-dqsG4tPEEI")

def get_hotel_booking_link(hotel_name):
    """Retrieve hotel booking link from Google Maps"""
    try:
        search_query = urllib.parse.quote(hotel_name)
        return f'<a href="https://www.google.com/maps/search/{search_query}" target="_blank">{hotel_name}</a>'
    except Exception as e:
        logging.error(f"Error retrieving hotel booking link: {e}")
        return hotel_name


def get_place_coordinates(place_name):
    """Retrieve coordinates of a place from Google Places API"""
    try:
        url = f"https://maps.googleapis.com/maps/api/place/textsearch/json?query={urllib.parse.quote(place_name)}&key={GOOGLE_MAPS_API_KEY}"
        response = requests.get(url).json()
        if response["status"] == "OK" and len(response["results"]) > 0:
            location = response["results"][0]["geometry"]["location"]
            return f'{location["lat"]},{location["lng"]}'
        return None
    except Exception as e:
        logging.error(f"Error retrieving place coordinates: {e}")
        return None


# Initialize Ollama chatbot
ollama_model = Ollama(model="llama3:latest")
prompt_template = ChatPromptTemplate.from_template(
    "You are a Thai travel planner assisting the user in planning their trip to Thailand.\n"
    "User's Request: {user_request}\n"
    "Chat History: {history}\n\n"
    "Instructions:\n"
    "1. If the user greets you with 'hi' or similar greetings, reply with: 'Hello! This is a Thailand trip planner. How can I assist you with your trip today?'.\n"
    "2. If the user asks for a hotel booking link, provide the link(s) directly, without generating a new travel plan or itinerary.\n"
    "3. If the user requests a trip plan, first ask how many days they plan to spend on their trip.\n"
    "4. After getting the number of days, generate a realistic travel itinerary for the specified number of days with specific places to visit each day, including popular attractions and recommended hotels in Thailand. The itinerary should be practical, with clear recommendations on places to visit, eat, and stay.\n"
    "5. At the end of the itinerary, list the primary location (city) of the trip and include a summary of the places and hotels mentioned in the itinerary. The format should be: 'Primary location: <location>', 'Places: <place1>, <place2>, ...', 'Hotels: <hotel1>, <hotel2>, ...'.\n"
    "Ensure that your recommendations are suitable for the user's preferences and provide a personalized travel experience."
)




output_parser = StrOutputParser()
chatbot_pipeline = prompt_template | ollama_model | output_parser

@app.route('/')
def main():
    return render_template('home.html')

@app.route('/index')
def chat_page():
    return render_template('index.html')

@socketio.on('send_message')
def handle_send_message(data):
    if not data or 'message' not in data:
        emit('receive_message', {'message': "Invalid request.", 'timestamp': datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')})
        return

    query_input = data['message']
    chat_history = session.get('history', [])
    
    try:
        history_text = "\n".join([f"{h[0]}: {h[1]}" for h in chat_history])
        ollama_response = chatbot_pipeline.invoke({
            "user_request": query_input,
            "history": history_text
        })
        
        # Extract places and hotels from Ollama response
        places_match = re.search(r"Places:\s*(.+)", ollama_response)
        hotels_match = re.search(r"Hotels:\s*(.+)", ollama_response)
        places_list = places_match.group(1).split(",") if places_match else []
        hotels_list = hotels_match.group(1).split(",") if hotels_match else []
        
        # Get coordinates for places
        coordinates = [get_place_coordinates(place.strip()) for place in places_list]
        coordinates = [c for c in coordinates if c is not None]
        
        # Create Google Maps Embed URL with multiple locations
        if coordinates:
            location_query = "|".join([f"{coord}" for coord in coordinates])
            maps_url = f"https://www.google.com/maps/embed/v1/place?key={GOOGLE_MAPS_API_KEY}&q={location_query}"
        else:
            maps_url = ""
        
        # Hotel booking links
        hotel_links = "<br>".join([get_hotel_booking_link(hotel.strip()) for hotel in hotels_list])

        response = ollama_response
        if maps_url:
            response += f"<div class='map-container'><iframe width='100%' height='400' style='border:0' loading='lazy' allowfullscreen src='{maps_url}'></iframe></div>"
        
        if hotel_links:
            response += f"<div class='hotel-recommendations'><h3>Booking links for hotels:</h3>{hotel_links}</div>"
        
        # Save the chat history and send the response
        chat_history.append(("user", query_input, datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')))
        chat_history.append(("system", response, datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')))
        session['history'] = chat_history
        session.modified = True
        
        emit('receive_message', {'message': response, 'timestamp': datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')})
    except Exception as e:
        logging.error(f"Error processing message: {e}")
        emit('receive_message', {'message': f"An error occurred: {str(e)}", 'timestamp': datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')})

if __name__ == '__main__':
    socketio.run(app, debug=True)