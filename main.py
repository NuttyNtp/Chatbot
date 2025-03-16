import requests
from flask import Flask, render_template, session, jsonify, send_file
from flask_socketio import SocketIO, emit
import logging
import datetime
import secrets
import os
import urllib.parse
import subprocess
from reportlab.lib.pagesizes import letter
from reportlab.pdfgen import canvas
import json
from bs4 import BeautifulSoup
import folium
from folium.plugins import MarkerCluster
import base64
from io import BytesIO
import re

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

# Google Integration for Places and Images
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
                return f"https://maps.googleapis.com/maps/api/place/photo?maxwidth=800&photoreference={photo_reference}&key={GOOGLE_MAPS_API_KEY}"
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

# Folium Map Integration 
class FoliumMapGenerator:
    @staticmethod
    def parse_itinerary_locations(itinerary_text, base_location_name):
        """
        Parse itinerary text to extract location names for mapping
        Returns a list of dictionaries with location names
        """
        locations = []
        
        # Add the main destination as the first location
        locations.append({"name": base_location_name, "is_base": True})
        
        # Extract locations from itinerary
        day_pattern = r'Day \d+:.*?(?=Day \d+:|$)'
        day_matches = re.findall(day_pattern, itinerary_text, re.DOTALL)
        
        for day_match in day_matches:
            # Extract activities with locations
            activity_lines = [line.strip() for line in day_match.split('\n') if line.strip()]
            
            for line in activity_lines:
                if ':' in line and not line.startswith('Day'):
                    # Skip the day header, look for activities with locations
                    activity_parts = line.split(',')
                    if len(activity_parts) >= 2:
                        location_name = activity_parts[1].strip()
                        if location_name and location_name != base_location_name:
                            locations.append({"name": f"{location_name}, {base_location_name}", "is_base": False})
        
        # Remove duplicates while preserving order
        unique_locations = []
        seen = set()
        for loc in locations:
            if loc["name"] not in seen:
                unique_locations.append(loc)
                seen.add(loc["name"])
                
        return unique_locations

    @staticmethod
    def generate_folium_map(locations):
        """
        Generate a Folium map with markers for all locations in the itinerary
        Returns HTML string of the map
        """
        # Default to Thailand coordinates if no locations provided
        default_lat, default_lon = 13.7563, 100.5018  # Bangkok, Thailand
        
        # Create a map centered on the first valid location
        map_center = [default_lat, default_lon]
        location_data = []
        all_coordinates = []
        
        for location in locations:
            place_info = GoogleIntegration.get_place_by_name(location["name"])
            if place_info:
                lat, lon = place_info['latitude'], place_info['longitude']
                all_coordinates.append([lat, lon])
                
                # Get image URL for the location
                image_url = GoogleIntegration.get_place_image_url(place_info['place_id'])
                
                location_data.append({
                    "name": place_info['name'],
                    "address": place_info['address'],
                    "lat": lat,
                    "lon": lon,
                    "is_base": location.get("is_base", False),
                    "image_url": image_url
                })
        
        # If we have valid coordinates, calculate the center
        if all_coordinates:
            avg_lat = sum(coord[0] for coord in all_coordinates) / len(all_coordinates)
            avg_lon = sum(coord[1] for coord in all_coordinates) / len(all_coordinates)
            map_center = [avg_lat, avg_lon]
        
        # Create base map
        m = folium.Map(location=map_center, zoom_start=10, tiles="CartoDB positron")
        
        # Add marker cluster
        marker_cluster = MarkerCluster().add_to(m)
        
        # Add markers for each location
        for loc in location_data:
            popup_html = f"""
            <div style="width:250px">
                <h4>{loc['name']}</h4>
                <p>{loc['address']}</p>
                {f'<img src="{loc["image_url"]}" style="width:100%;max-height:150px;object-fit:cover">' if loc.get('image_url') else ''}
            </div>
            """
            
            # Different icon for base location vs. activity locations
            if loc.get("is_base"):
                icon = folium.Icon(color="red", icon="home", prefix="fa")
            else:
                icon = folium.Icon(color="blue", icon="info-sign")
                
            folium.Marker(
                location=[loc['lat'], loc['lon']],
                popup=folium.Popup(popup_html, max_width=300),
                tooltip=loc['name'],
                icon=icon
            ).add_to(marker_cluster)
        
        # Save map to HTML string
        map_html = m._repr_html_()
        
        return map_html, location_data

# Ollama Integration for AI-Powered Trip Planning
class OllamaChatbot:
    @staticmethod
    def is_food_query(query):
        """Check if the query is food-related"""
        food_keywords = ['food', 'dish', 'eat', 'cuisine', 'restaurant', 'meal', 'thai food', 'spicy', 'dessert']
        return any(keyword in query.lower() for keyword in food_keywords)

    @staticmethod
    def get_food_recommendations(query, history=None):
        """Handle food-specific queries with detailed Thai cuisine information"""
        try:
            # Extract dietary preferences from history
            preferences = ""
            if history and len(history) > 0:
                for entry in history[-5:]:
                    if 'user' in entry and any(word in entry['user'].lower() for word in ['vegetarian', 'spicy', 'allergic', 'vegan']):
                        preferences += f"User preference: {entry['user']}\n"

            prompt = f"""
            You are a Thai cuisine expert. Provide detailed recommendations for authentic Thai dishes.

            Previous preferences: {preferences}

            Query: {query}

            Format your response as follows:
            Must-Try Thai Dishes:
            1. [Thai name] - [English name]
            - Description: Brief explanation of the dish
            - Key ingredients: Main components
            - Spice level: [Mild/Medium/Hot]
            - Price range: ฿[range]
            - Where to find: Recommended places in Thailand
            - Cultural significance: Brief cultural context

            Please recommend 4-5 dishes with a mix of:
            - Main dishes
            - Street food
            - Desserts or snacks
            - Regional specialties
            """

            # Process with Ollama
            result = subprocess.run(["ollama", "run", "llama3.1:latest", prompt],
                                  capture_output=True, text=True, timeout=60,
                                  cwd=os.path.dirname(os.path.abspath(__file__)))

            if result.returncode == 0 and result.stdout.strip():
                return result.stdout.strip()
            else:
                return "I apologize, but I'm having trouble generating food recommendations right now. Please try again."

        except Exception as e:
            logging.error(f"Error in food recommendations: {str(e)}")
            return "Sorry, I couldn't process your food query. Please try again."

    @staticmethod
    def get_travel_plan(query, history=None):
        # Check if this is a food-related query
        if OllamaChatbot.is_food_query(query):
            return OllamaChatbot.get_food_recommendations(query, history)

        try:
            # Build the conversation context from history with user preferences
            context = ""
            user_preferences = {}
            if history and len(history) > 0:
                for entry in history[-5:]:
                    if 'user' in entry:
                        context += f"User: {entry['user']}\n"
                        # Extract user preferences from messages
                        message = entry['user'].lower()
                        if 'budget' in message:
                            user_preferences['budget'] = 'budget-conscious'
                        if 'luxury' in message:
                            user_preferences['budget'] = 'luxury'
                        if 'family' in message:
                            user_preferences['travel_style'] = 'family'
                        if 'adventure' in message:
                            user_preferences['travel_style'] = 'adventure'
                        if 'culture' in message:
                            user_preferences['interests'] = 'cultural'
                        if 'food' in message:
                            user_preferences['interests'] = 'culinary'
                    if 'assistant' in entry:
                        context += f"Assistant: {entry['assistant']}\n"
            
            # Enhance prompt with user preferences
            preference_context = ""
            if user_preferences:
                preference_context = "Based on your preferences: \n"
                for key, value in user_preferences.items():
                    preference_context += f"- {key.replace('_', ' ').title()}: {value}\n"
            
            prompt = f"""
            You are a concise Thailand travel expert. Focus on providing practical, specific recommendations.

            Previous context: {context}
            {preference_context}

            Create a focused travel plan for: {query}

            Guidelines:
            - Recommend real locations with addresses
            - Include local food spots with Thai names and prices
            - Add transport options and costs
            - Mention cultural tips and safety advice

            Format (keep it brief):
            Welcome to {query}!
            [2-3 sentence overview]

            Highlights (3-4 must-visit spots):
            1. [Name] - [Why visit, practical tips]
            2. [Name] - [Why visit, practical tips]
            3. [Name] - [Why visit, practical tips]

            Local Food Guide:
            - [Restaurant name]: [Signature dish] (฿price)
            - [Restaurant name]: [Signature dish] (฿price)

            Getting Around:
            - [Transport option]: [Cost, tips]
            - [Transport option]: [Cost, tips]

            Cultural Tips:
            - [2-3 essential customs]
            - [2-3 safety tips]

            Where to Stay:
            - [Area name]: [Hotel suggestion, price range]
            """

            
            logging.info(f"Sending prompt to Ollama for query: {query}")
            
            try:
                # Check if Ollama is running and available
                test_cmd = subprocess.run(["ollama", "list"], capture_output=True, text=True, timeout=10)
                if test_cmd.returncode != 0:
                    logging.error("Ollama service is not running or responding")
                    return "Error: Ollama service is not available. Please ensure Ollama is running."
                
                logging.info(f"Available Ollama models: {test_cmd.stdout}")
                
                # Run Ollama with improved error handling and timeout
                result = subprocess.run(["ollama", "run", "llama3.1:latest", prompt],
                                      capture_output=True, text=True, timeout=180,  # Increased timeout
                                      cwd=os.path.dirname(os.path.abspath(__file__)))
                
                # Process Ollama response with improved error handling
                if result.returncode != 0:
                    error_msg = result.stderr.strip() if result.stderr else "Unknown error"
                    logging.error(f"Ollama process failed with error: {error_msg}")
                    return f"Error: Unable to generate travel plan. {error_msg}"
                
                response = result.stdout.strip()
                if not response:
                    logging.error("Ollama returned empty response")
                    return "Error: No response received from Ollama. Please try again."
                
                if result.stderr:
                    logging.warning(f"Ollama warnings: {result.stderr}")
                
                # Validate response format
                if len(response.split('\n')) < 5:  # Basic validation for minimum content
                    logging.warning("Ollama response seems incomplete")
                    return "Error: Generated travel plan seems incomplete. Please try again."
                
                logging.info("Successfully generated travel plan with Ollama")
                return result.stdout.strip()
                
            except FileNotFoundError:
                logging.error("Ollama command not found. Is Ollama installed?")
                return "Error: Ollama is not installed on the server. Please contact support."
                
            except subprocess.TimeoutExpired as e:
                logging.error(f"Ollama process timed out after {e.timeout} seconds")
                try:
                    subprocess.run(["pkill", "-f", "ollama"])  # Kill any running Ollama processes
                    logging.info("Successfully terminated timed out Ollama process")
                except Exception as kill_error:
                    logging.error(f"Error killing timed out process: {kill_error}")
                return "Error: Travel plan generation timed out. Please try a simpler query or try again later."
                
            except Exception as e:
                logging.error(f"Unexpected error in Ollama process: {str(e)}")
                return "Error: An unexpected error occurred. Please try again later."
                
        except Exception as e:
            logging.error(f"General error in get_travel_plan: {str(e)}")
            return "Sorry, an error occurred while creating travel plan."


# Destination Details Generator
class DestinationDetailsGenerator:
    @staticmethod
    def generate_comprehensive_details(destination_name, history=None):
        """
        Generate comprehensive details for a destination, including AI itinerary,
        Folium map embed, place images, and hotel booking link.
        This combines information from Ollama and Google APIs.
        """
        # Retrieve Ollama's AI-generated travel plan
        ai_itinerary = OllamaChatbot.get_travel_plan(f"Plan a trip to {destination_name}", history)

        # Get destination details from Google API
        dest_info = GoogleIntegration.get_place_by_name(destination_name)
        if not dest_info:
            return f"Oops! I couldn't find anything about {destination_name}. Maybe try a different place?"

        # Parse locations from the itinerary
        locations = FoliumMapGenerator.parse_itinerary_locations(ai_itinerary, destination_name)
        
        # Generate Folium map with all locations
        folium_map_html, location_data = FoliumMapGenerator.generate_folium_map(locations)

        # Get main destination image
        main_image_url = GoogleIntegration.get_place_image_url(dest_info['place_id'])

        # Get Hotel Booking Link
        hotel_booking_link = GoogleIntegration.get_hotel_booking_link(destination_name)

        # Create location gallery HTML
        location_gallery_html = ""
        for loc in location_data:
            if loc.get('image_url'):
                location_gallery_html += f"""
                <div class="location-card">
                    <img src="{loc['image_url']}" alt="{loc['name']}" class="location-image"/>
                    <div class="location-info">
                        <h4>{loc['name']}</h4>
                        <p>{loc['address']}</p>
                    </div>
                </div>
                """

        # Prepare HTML response with place details under the image
        response = f"""
        <div class="destination-details-container">
            <h2>Excited to Explore {dest_info['name']}? Here's Your Travel Itinerary!</h2>
            
            <div class="destination-overview">
                <div class="destination-hero">
                    {f'<img src="{main_image_url}" alt="{dest_info["name"]} Image" class="hero-image"/>' if main_image_url else ''}
                    <div class="destination-description">
                        <h3>{dest_info['name']}</h3>
                        <p><strong>Address:</strong> {dest_info['address']}</p>
                        <p><strong>Coordinates:</strong> {dest_info['latitude']}, {dest_info['longitude']}</p>
                        <a href="{hotel_booking_link}" target="_blank" class="book-button">Find your perfect hotel here!</a>
                    </div>
                </div>
            </div>

            <div class="itinerary-section">
                <h3>Your Adventure Awaits!</h3>
                <pre>{ai_itinerary}</pre>
            </div>

            <div class="map-container">
                <h3>Interactive Trip Map</h3>
                <div class="folium-map">{folium_map_html}</div>
            </div>

            <div class="location-gallery">
                <h3>Featured Places You Shouldn't Miss</h3>
                <div class="gallery-container">
                    {location_gallery_html}
                </div>
            </div>

            <style>
                .destination-details-container {{
                    font-family: 'Arial', sans-serif;
                    max-width: 1200px;
                    margin: 0 auto;
                }}
                .destination-overview {{
                    margin-bottom: 30px;
                }}
                .destination-hero {{
                    display: flex;
                    flex-wrap: wrap;
                    gap: 20px;
                    align-items: center;
                }}
                .hero-image {{
                    max-width: 400px;
                    border-radius: 8px;
                    box-shadow: 0 4px 8px rgba(0,0,0,0.1);
                }}
                .destination-description {{
                    flex: 1;
                    min-width: 300px;
                }}
                .book-button {{
                    display: inline-block;
                    background-color: #4CAF50;
                    color: white;
                    padding: 10px 15px;
                    text-decoration: none;
                    border-radius: 4px;
                    margin-top: 10px;
                }}
                .itinerary-section {{
                    background-color: #f9f9f9;
                    padding: 20px;
                    border-radius: 8px;
                    margin-bottom: 30px;
                }}
                .map-container {{
                    height: 500px;
                    margin-bottom: 30px;
                }}
                .folium-map {{
                    height: 100%;
                    border-radius: 8px;
                    overflow: hidden;
                }}
                .location-gallery {{
                    margin-bottom: 30px;
                }}
                .gallery-container {{
                    display: grid;
                    grid-template-columns: repeat(auto-fill, minmax(280px, 1fr));
                    gap: 20px;
                }}
                .location-card {{
                    border-radius: 8px;
                    overflow: hidden;
                    box-shadow: 0 4px 8px rgba(0,0,0,0.1);
                }}
                .location-image {{
                    width: 100%;
                    height: 180px;
                    object-fit: cover;
                }}
                .location-info {{
                    padding: 15px;
                }}
                .location-info h4 {{
                    margin-top: 0;
                    margin-bottom: 8px;
                }}
                .location-info p {{
                    margin: 0;
                    color: #666;
                }}
            </style>
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
        text_content = "Travel History:\n\n"
        for message in conversation_history[session_id]:
            if 'user' in message:
                text_content += f"Question: {message['user']}\n"
            elif 'assistant' in message:
                text_content += f"Answer: {message['assistant']}\n\n"

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
    session_id = data.get('session_id', str(datetime.datetime.now().timestamp()))
    logging.info(f"User message: {user_message} (Session: {session_id})")
    
    if session_id not in conversation_history:
        conversation_history[session_id] = []
    
    # Store user message in conversation history
    conversation_history[session_id].append({'user': user_message})
    # Check if the user wants to save the conversation as a PDF
    if "save pdf" in user_message.lower():
        # Assume the user is asking to save their travel plan as a PDF
        destination_name = "Thailand Trip"  # You can extract the destination name from the user's message if necessary
        pdf_path = create_pdf_from_history(session_id, destination_name)
        
        if pdf_path:
            # Send the PDF back to the user
            emit('receive_message', {'message': f"Your travel plan PDF has been generated: {pdf_path}"})
        else:
            emit('receive_message', {'message': "Sorry, there was an issue generating the PDF."})
    else:
        # If the message is not about saving as PDF, continue generating travel plan
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