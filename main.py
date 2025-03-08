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
                # Format the history as a conversation for context
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
        
        # Add a horizontal line
        c.line(72, height - 100, width - 72, height - 100)
        
        # Extract the plan content from conversation history
        plan_content = ""
        for entry in conversation_history[session_id]['messages']:
            if 'assistant' in entry and entry['assistant']:
                # Extract text from HTML content
                text_content = extract_text_from_html(entry['assistant'])
                if text_content and "AI-Powered Itinerary" in entry['assistant']:
                    plan_content = text_content
                    break
        
        # If no specific itinerary found, compile all assistant responses
        if not plan_content:
            all_content = []
            for entry in conversation_history[session_id]['messages']:
                if 'assistant' in entry:
                    text = extract_text_from_html(entry['assistant'])
                    all_content.append(text)
            plan_content = "\n\n".join(all_content)
        
        # Write content to PDF
        c.setFont("Helvetica", 12)
        y_position = height - 120
        text_object = c.beginText(72, y_position)
        text_object.setFont("Helvetica", 12)
        
        # Split by lines and add with proper spacing
        for line in plan_content.split('\n'):
            text_object.textLine(line)
            
        c.drawText(text_object)
        c.save()
        
        return pdf_path
        
    except Exception as e:
        logging.error(f"Error creating PDF: {e}")
        return None


# New function to check if this is a follow-up question
def is_followup_question(message, current_destinations):
    """
    Determine if the message is a follow-up question about a destination
    by checking for context-dependent phrases.
    """
    followup_indicators = [
        "how about", "what about", "can you tell me more", "what's the best", 
        "how many days", "where should i stay", "when is the best time", 
        "how do i get", "is it worth", "should i visit", "how much",
        "what are the", "can i", "do they", "is there", "are there",
        "tell me more", "recommend", "suggestions", "options", "alternatives"
    ]
    
    # Convert to lowercase
    message_lower = message.lower()
    
    # Check for pronouns and other context-dependent words
    has_pronouns = any(word in message_lower for word in ["there", "it", "that place", "this", "these", "those"])
    
    # Check for follow-up question indicators
    has_followup_indicators = any(indicator in message_lower for indicator in followup_indicators)
    
    # If message contains a destination name from current context, it's likely not a follow-up
    contains_destination = any(destination.lower() in message_lower for destination in current_destinations)
    
    # Return True if it seems like a follow-up question
    return (has_pronouns or has_followup_indicators) and not contains_destination


# Session initialization
@socketio.on('connect')
def handle_connect():
    """Handle client connection by creating a new conversation session"""
    session_id = request.sid
    conversation_history[session_id] = {
        'messages': [],
        'current_destination': None,
        'last_itinerary': None  # Store the last generated itinerary
    }
    logging.info(f"New client connected: {session_id}")
    emit('session_initialized', {'session_id': session_id})


# Chatbot Handler with session history and improved PDF export
@socketio.on('send_message')
def handle_send_message(data):
    try:
        session_id = request.sid
        
        # Initialize session if it doesn't exist
        if session_id not in conversation_history:
            conversation_history[session_id] = {
                'messages': [],
                'current_destination': None,
                'last_itinerary': None
            }
        
        if not data or 'message' not in data:
            emit('receive_message', {
                'message': "I couldn't understand your request. Could you please rephrase?", 
                'timestamp': datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')
            })
            return

        query_input = data['message'].strip()
        user_history = conversation_history[session_id]['messages']
        current_destinations = [conversation_history[session_id]['current_destination']] if conversation_history[session_id]['current_destination'] else []
        
        # Store user message
        user_history.append({'user': query_input})
        
        # Check for "Save PDF" command with simpler syntax
        pdf_match = re.match(r"(save pdf|save as pdf|export pdf|export as pdf|download pdf)(?:\s+for\s+(.+))?", query_input, re.IGNORECASE)
        if pdf_match:
            # If a destination is specified in the command, use it
            # Otherwise, use the current destination from the conversation
            specified_destination = pdf_match.group(2)
            destination_name = specified_destination.strip() if specified_destination else conversation_history[session_id]['current_destination']
            
            if not destination_name:
                response = "I'm not sure which destination you want to save. Could you please specify a destination, for example: 'Save PDF for Bangkok'?"
                
                # Store assistant response
                user_history.append({'assistant': response})
                
                emit('receive_message', {
                    'message': response, 
                    'timestamp': datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')
                })
                return
            
            # Create PDF from the conversation history
            pdf_path = create_pdf_from_history(session_id, destination_name)
            
            if pdf_path:
                response = f"Your travel plan for {destination_name} has been saved as a PDF. You can download it here: /{pdf_path}"
            else:
                response = "There was an error saving the travel plan as a PDF."
            
            # Store assistant response
            user_history.append({'assistant': response})
            
            emit('receive_message', {
                'message': response, 
                'timestamp': datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')
            })
            return
            
        # Check if this is a follow-up question
        is_followup = is_followup_question(query_input, current_destinations)
        
        if is_followup and conversation_history[session_id]['current_destination']:
            # Use the existing destination context
            destination = conversation_history[session_id]['current_destination']
            
            # Generate a contextual response using history
            ai_response = OllamaChatbot.get_travel_plan(query_input, user_history)
            response = f"<div class='follow-up-response'><h3>About {destination}:</h3><pre>{ai_response}</pre></div>"
        else:
            # Extract potential new destination from the query
            # Simple extraction - we assume the destination is the main focus of the query
            potential_destination = query_input
            if "to " in query_input.lower():
                potential_destination = query_input.lower().split("to ", 1)[1].split("?")[0].split(".")[0].strip()
                
            # Update current destination
            conversation_history[session_id]['current_destination'] = potential_destination
                
            # Generate comprehensive details
            response = DestinationDetailsGenerator.generate_comprehensive_details(potential_destination, user_history)
            
            # Store this as the last itinerary for this session
            conversation_history[session_id]['last_itinerary'] = response
        
        # Store assistant response
        user_history.append({'assistant': response})
        
        # Keep history to a reasonable size (last 20 messages)
        if len(user_history) > 20:
            conversation_history[session_id]['messages'] = user_history[-20:]
            
        emit('receive_message', {
            'message': response, 
            'timestamp': datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        })

    except Exception as e:
        logging.error(f"Chatbot processing error: {e}")
        emit('receive_message', {
            'message': "I apologize, but I'm having trouble processing your request. Could you try again?", 
            'timestamp': datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        })


# Add session management routes
@app.route('/get_history')
def get_history():
    """
    Get the conversation history for the current session
    """
    session_id = request.args.get('session_id')
    if session_id in conversation_history:
        return jsonify(conversation_history[session_id]['messages'])
    return jsonify([])


@app.route('/clear_history')
def clear_history():
    """
    Clear the conversation history for the current session
    """
    session_id = request.args.get('session_id')
    if session_id in conversation_history:
        conversation_history[session_id]['messages'] = []
        conversation_history[session_id]['current_destination'] = None
        conversation_history[session_id]['last_itinerary'] = None
        return jsonify({"status": "success"})
    return jsonify({"status": "error", "message": "Session not found"})


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


# Run Flask App
if __name__ == '__main__':
    socketio.run(app, debug=True)