import requests
from flask import Flask, render_template, session, request, jsonify, send_file
from flask_socketio import SocketIO, emit
import logging
import datetime
import secrets
import os
import urllib.parse
import subprocess
from reportlab.lib.pagesizes import letter
from reportlab.pdfgen import canvas
import re
import json
from bs4 import BeautifulSoup

# Setup logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s: %(message)s')

# Create Flask app
app = Flask(__name__)
app.secret_key = secrets.token_hex(16)

# Initialize SocketIO
socketio = SocketIO(app, cors_allowed_origins="*")

# Google API Key (Don't forget to set your API Key) 
GOOGLE_MAPS_API_KEY = os.getenv("GOOGLE_MAPS_API_KEY", "AIzaSyDv_OEg50nhbpvW-EtNy3ze-dqsG4tPEEI")

# In-memory session storage - will be replaced with user sessions
conversation_history = {}

# Google Integration for Maps, Images, and Hotels
class GoogleIntegration:
    @staticmethod
    def get_place_by_name(destination_name):
        """
        Search for a place by name using Google Places API
        It returns the place's name, address, latitude, longitude, and place_id.
        """
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
        logging.error("Google API request failed or no results found.")
        return None

    @staticmethod
    def generate_google_maps_embed(latitude, longitude):
        """
        Generate an embedded Google Map with a marker using latitude and longitude.
        Returns the embed code as a string.
        """
        return f"""
        <iframe width="600" height="450" frameborder="0" style="border:0" 
        src="https://www.google.com/maps/embed/v1/place?key={GOOGLE_MAPS_API_KEY}&q={latitude},{longitude}" 
        allowfullscreen></iframe>
        """

    @staticmethod
    def get_place_image_url(place_id):
        """
        Fetch an image URL from Google Places API using the place_id.
        Returns the image URL as a string.
        """
        url = f"https://maps.googleapis.com/maps/api/place/details/json?placeid={place_id}&key={GOOGLE_MAPS_API_KEY}"
        response = requests.get(url)

        if response.status_code == 200:
            data = response.json()
            if 'result' in data and 'photos' in data['result']:
                photo_reference = data['result']['photos'][0]['photo_reference']
                return f"https://maps.googleapis.com/maps/api/place/photo?maxwidth=400&photoreference={photo_reference}&key={GOOGLE_MAPS_API_KEY}"
        logging.error("Failed to fetch place image.")
        return None

    @staticmethod
    def get_hotel_booking_link(destination_name):
        """
        Generate a hotel booking link for the destination.
        It encodes the destination name into the URL for Booking.com.
        """
        destination_encoded = urllib.parse.quote(destination_name)
        return f"https://www.booking.com/searchresults.html?ss={destination_encoded}"

# Ollama Integration for AI-Powered Trip Planning
class OllamaChatbot:
    @staticmethod
    def get_travel_plan(query, history=None):
        """
        Query Ollama for a structured travel itinerary based on the provided query.
        The query should specify a travel destination, and Ollama generates the itinerary.
        Now includes conversation history for context.
        """
        try:
            # Build the conversation context from history
            context = ""
            if history and len(history) > 0:
                for entry in history[-5:]:  # Only use the last 5 exchanges to keep prompt size reasonable
                    if 'user' in entry:
                        context += f"User: {entry['user']}\n"
                    if 'assistant' in entry:
                        context += f"Assistant: {entry['assistant']}\n"
            
            prompt = f"""
            You are a Thailand travel expert. 

            {context}

            Plan a detailed trip itinerary for: {query}.
            Consider the previous conversation context when responding.
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
    def generate_comprehensive_details(destination_name, history=None):
        """
        Generate comprehensive details for a destination, including AI itinerary,
        Google Maps embed, place image, and hotel booking link.
        This combines information from Ollama and Google APIs.
        Now includes conversation history for context.
        """
        # Retrieve Ollama's AI-generated travel plan
        ai_itinerary = OllamaChatbot.get_travel_plan(f"Plan a trip to {destination_name}", history)

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

        # Prepare HTML response with place details under the image
        response = f"""
        <div class="destination-details-container">
            <h2>{dest_info['name']} - Travel Itinerary</h2>
            
            <div class="itinerary-section">
                <h3>AI-Powered Itinerary</h3>
                <pre>{ai_itinerary}</pre>
            </div>

            <div class="destination-images-and-info">
                <h3>Destination Image</h3>
                {f'<img src="{image_url}" alt="{dest_info["name"]} Image" class="destination-image"/>' if image_url else ''}
                <div class="destination-description">
                    <p><strong>Address:</strong> {dest_info['address']}</p>
                    <p><strong>Coordinates:</strong> {dest_info['latitude']}, {dest_info['longitude']}</p>
                </div>
            </div>

            <div class="destination-location">
                <h3>Location</h3>
                <div class="google-maps-embed">{google_maps_embed}</div>
            </div>

            <div class="hotel-booking">
                <h3>Book Your Stay</h3>
                <a href="{hotel_booking_link}" target="_blank">Find hotels in {dest_info['name']}</a>
            </div>
        </div>
        """
        return response


# Extract text content from HTML for PDF
def extract_text_from_html(html_content):
    """
    Extract readable text content from HTML for PDF generation
    """
    try:
        soup = BeautifulSoup(html_content, 'html.parser')
        
        # Extract the itinerary section specifically
        itinerary_section = soup.select_one('.itinerary-section pre')
        if itinerary_section:
            return itinerary_section.get_text()
            
        # If no specific section found, try to get all text
        return soup.get_text(separator='\n', strip=True)
    except Exception as e:
        logging.error(f"Error extracting text from HTML: {e}")
        return html_content  # Return original content if parsing fails


# Function to generate PDF from conversation history
def create_pdf_from_history(session_id, destination_name):
    """
    Generate PDF file from the conversation history
    """
    try:
        if session_id not in conversation_history:
            return None
            
        # PDF filename
        pdf_filename = f"{destination_name.replace(' ', '_')}_travel_plan.pdf"
        
        # PDF path to save
        pdf_path = os.path.join('static', pdf_filename)
        
        # Create directory if it doesn't exist
        os.makedirs('static', exist_ok=True)
        
        c = canvas.Canvas(pdf_path, pagesize=letter)
        width, height = letter
        
        c.setFont("Helvetica-Bold", 16)
        c.drawString(72, height - 72, f"Travel Plan for {destination_name}")
        c.setFont("Helvetica", 10)
        c.drawString(72, height - 90, f"Generated on: {datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        
        # Extract text content for the PDF
        text_content = extract_text_from_html(conversation_history[session_id])

        text_object = c.beginText(72, height - 120)
        text_object.setFont("Helvetica", 10)
        text_object.setTextOrigin(72, height - 120)
        text_object.textLines(text_content)
        
        c.drawText(text_object)
        c.save()

        return pdf_path
    except Exception as e:
        logging.error(f"Error generating PDF: {e}")
        return None


# SocketIO message handling
@socketio.on('send_message')
def handle_message(data):
    user_message = data['message']
    session_id = request.sid
    logging.info(f"User message: {user_message} (Session: {session_id})")
    
    if session_id not in conversation_history:
        conversation_history[session_id] = []
    
    # Store user message in conversation history
    conversation_history[session_id].append({'user': user_message})
    
    # Call the AI chatbot to get the travel plan
    destination_name = user_message  # Assume user is asking about a destination
    generated_details = DestinationDetailsGenerator.generate_comprehensive_details(destination_name, conversation_history[session_id])
    
    # Store assistant response in conversation history
    conversation_history[session_id].append({'assistant': generated_details})

    # Send the response back to the client
    emit('receive_message', {'message': generated_details})


# PDF download route
@app.route('/download_pdf/<session_id>/<destination_name>', methods=['GET'])
def download_pdf(session_id, destination_name):
    pdf_path = create_pdf_from_history(session_id, destination_name)
    if pdf_path:
        return send_file(pdf_path, as_attachment=True)
    else:
        return jsonify({"error": "Failed to generate PDF"}), 400

# Flask Routes
@app.route('/')
def main():
    """
    Route to display the home page.
    """
    return render_template('home.html')

@app.route('/index')
def chat_page():
    """
    Route to display the chat page where users can interact with the chatbot.
    """
    return render_template('index.html')

if __name__ == '__main__':
    socketio.run(app, debug=True)