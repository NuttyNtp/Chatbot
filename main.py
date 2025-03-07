import requests
from flask import Flask, render_template, session, request
from flask_socketio import SocketIO, emit
import logging
import datetime
import secrets
import os
import urllib.parse
import subprocess

# Setup logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s: %(message)s')

# Create Flask app
app = Flask(__name__)
app.secret_key = secrets.token_hex(16)

# Initialize SocketIO
socketio = SocketIO(app, cors_allowed_origins="*")

# Google API Key (Don't forget to set your API Key)
GOOGLE_MAPS_API_KEY = os.getenv("GOOGLE_MAPS_API_KEY", "AIzaSyDv_OEg50nhbpvW-EtNy3ze-dqsG4tPEEI")


# Google Integration for Maps, Images, and Hotels
class GoogleIntegration:
    @staticmethod
    def get_place_by_name(destination_name):
        """Search for a place by name using Google Places API"""
        url = f"https://maps.googleapis.com/maps/api/place/textsearch/json?query={destination_name}&key={GOOGLE_MAPS_API_KEY}"
        response = requests.get(url)

        if response.status_code == 200:
            data = response.json()
            if 'results' in data and len(data['results']) > 0:
                place = data['results'][0]  # Take the first result
                return {
                    'name': place.get('name'),
                    'address': place.get('formatted_address', 'No address available'),
                    'latitude': place['geometry']['location']['lat'],
                    'longitude': place['geometry']['location']['lng'],
                    'place_id': place['place_id']
                }
        return None

    @staticmethod
    def generate_google_maps_embed(latitude, longitude):
        """Generate an embedded Google Map with a marker"""
        return f"""
        <iframe width="600" height="450" frameborder="0" style="border:0" 
        src="https://www.google.com/maps/embed/v1/place?key={GOOGLE_MAPS_API_KEY}&q={latitude},{longitude}" 
        allowfullscreen></iframe>
        """

    @staticmethod
    def get_place_image_url(place_id):
        """Fetch an image URL from Google Places API"""
        url = f"https://maps.googleapis.com/maps/api/place/details/json?placeid={place_id}&key={GOOGLE_MAPS_API_KEY}"
        response = requests.get(url)

        if response.status_code == 200:
            data = response.json()
            if 'result' in data and 'photos' in data['result']:
                photo_reference = data['result']['photos'][0]['photo_reference']
                return f"https://maps.googleapis.com/maps/api/place/photo?maxwidth=400&photoreference={photo_reference}&key={GOOGLE_MAPS_API_KEY}"
        return None

    @staticmethod
    def get_hotel_booking_link(destination_name):
        """Generate a hotel booking link for the destination"""
        destination_encoded = urllib.parse.quote(destination_name)
        return f"https://www.booking.com/searchresults.html?ss={destination_encoded}"


# Ollama Integration for AI-Powered Trip Planning
class OllamaChatbot:
    @staticmethod
    def get_travel_plan(query):
        """Query Ollama for a structured travel itinerary"""
        try:
            prompt = f"""
            You are a Thailand travel expert. Plan a detailed trip itinerary for: {query}.
            Please format the answer like this:
            - Day 1: Activity, Location, Time
            - Day 2: Activity, Location, Time
            - Include hotel recommendations and travel tips.
            """
            result = subprocess.run(["ollama", "run", "llama3.1:latest", prompt], capture_output=True, text=True)
            return result.stdout.strip()
        except Exception as e:
            logging.error(f"Ollama error: {e}")
            return "Sorry, I couldn't generate an itinerary at the moment."



# Destination Details Generator
class DestinationDetailsGenerator:
    @staticmethod
    def generate_comprehensive_details(destination_name):
        """Generate destination details including AI itinerary, Google Maps, and Hotels"""
        # Retrieve Ollama's AI-generated travel plan
        ai_itinerary = OllamaChatbot.get_travel_plan(f"Plan a trip to {destination_name}")

        # Get destination details from Google API
        dest_info = GoogleIntegration.get_place_by_name(destination_name)
        if not dest_info:
            return f"Sorry, I couldn't find information for {destination_name}."

        # Generate Google Maps embed
        google_maps_embed = GoogleIntegration.generate_google_maps_embed(dest_info['latitude'], dest_info['longitude'])

        # Get Place Image
        image_url = GoogleIntegration.get_place_image_url(dest_info['place_id'])

        # Get Hotel Booking Link
        hotel_booking_link = GoogleIntegration.get_hotel_booking_link(destination_name)

        # Prepare HTML response
        response = f"""
        <div class="destination-details-container">
            <h2>{dest_info['name']} - Travel Itinerary</h2>
            
            <div class="itinerary-section">
                <h3>AI-Powered Itinerary</h3>
                <pre>{ai_itinerary}</pre>
            </div>

            <div class="destination-description">
                <p><strong>Address:</strong> {dest_info['address']}</p>
            </div>

            <div class="destination-location">
                <h3>Location</h3>
                <p><strong>Coordinates:</strong> {dest_info['latitude']}, {dest_info['longitude']}</p>
                <div class="google-maps-embed">{google_maps_embed}</div>
            </div>

            <div class="destination-images">
                <h3>Destination Image</h3>
                {f'<img src="{image_url}" alt="{dest_info["name"]} Image" class="destination-image"/>' if image_url else ''}
            </div>

            <div class="hotel-booking">
                <h3>Book Your Stay</h3>
                <a href="{hotel_booking_link}" target="_blank">Find hotels in {dest_info['name']}</a>
            </div>
        </div>
        """
        return response


# Chatbot Handler
@socketio.on('send_message')
def handle_send_message(data):
    try:
        if not data or 'message' not in data:
            socketio.emit('receive_message', {
                'message': "I couldn't understand your request. Could you please rephrase?", 
                'timestamp': datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')
            })
            return

        query_input = data['message'].strip()

        # Generate travel details
        response = DestinationDetailsGenerator.generate_comprehensive_details(query_input)

        # Emit response
        socketio.emit('receive_message', {
            'message': response, 
            'timestamp': datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        })

    except Exception as e:
        logging.error(f"Chatbot processing error: {e}")
        socketio.emit('receive_message', {
            'message': "I apologize, but I'm having trouble processing your request. Could you try again?", 
            'timestamp': datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        })


# Flask Routes
@app.route('/')
def main():
    return render_template('home.html')

@app.route('/index')
def chat_page():
    return render_template('index.html')


# Run Flask App
if __name__ == '__main__':
    socketio.run(app, debug=True)
