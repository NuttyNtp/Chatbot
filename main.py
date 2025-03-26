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
        Search for a place by name using Google Places API.
        Returns the place's name, address, latitude, longitude, and place_id.
        """
        url = f"https://maps.googleapis.com/maps/api/place/textsearch/json?query={destination_name}&components=country:TH&key={GOOGLE_MAPS_API_KEY}"
        response = requests.get(url)
        if response.status_code == 200:
            data = response.json()
            if 'results' in data and len(data['results']) > 0:
                place = data['results'][0]
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
    def get_hotel_booking_links(destination_name):
        """
        Generate hotel booking links for multiple platforms.
        """
        destination_encoded = urllib.parse.quote(destination_name)
        links = {
            "Booking.com": f"https://www.booking.com/searchresults.html?ss={destination_encoded}&dest_id=293406&dest_type=country",
        }
        return links

# Folium Map Integration
class FoliumMapGenerator:
    @staticmethod
    def parse_itinerary_locations(itinerary_text, base_location_name):
        """
        Parse itinerary text to extract location names and activities.
        Returns a list of dictionaries with location details.
        """
        locations = [{"name": base_location_name, "is_base": True, "activity": f"Main Destination: {base_location_name}"}]
        place_patterns = {
            "temple": r"(?:วัด|temple)\s*([\w\s]+)",
            "mountain": r"(?:ภูเขา|mountain)\s*([\w\s]+)",
            "market": r"(?:ตลาด|market)\s*([\w\s]+)",
            "hotel": r"(?:โรงแรม|hotel)\s*([\w\s]+)",
            "beach": r"(?:ชายหาด|beach)\s*([\w\s]+)",
            "general": r"at\s+([\w\s]+)"
        }
        day_pattern = r'Day \d+:.*?(?=Day \d+:|$)'
        day_matches = re.findall(day_pattern, itinerary_text, re.DOTALL)
        for day_match in day_matches:
            activity_lines = [line.strip() for line in day_match.split('\n') if line.strip()]
            for line in activity_lines:
                matched = False
                for place_type, pattern in place_patterns.items():
                    match = re.search(pattern, line, re.IGNORECASE)
                    if match:
                        location_name = match.group(1).strip()
                        if location_name and location_name != base_location_name:
                            locations.append({
                                "name": f"{location_name}, {base_location_name}",
                                "type": place_type,
                                "activity": line,
                                "is_base": False
                            })
                        matched = True
                        break
                if not matched:
                    general_match = re.search(place_patterns["general"], line, re.IGNORECASE)
                    if general_match:
                        location_name = general_match.group(1).strip()
                        if location_name and location_name != base_location_name:
                            locations.append({
                                "name": f"{location_name}, {base_location_name}",
                                "type": "general",
                                "activity": line,
                                "is_base": False
                            })
        unique_locations = []
        seen = set()
        for loc in locations:
            if loc["name"] not in seen:
                unique_locations.append(loc)
                seen.add(loc["name"])
        return unique_locations

    @staticmethod
    def generate_folium_map(locations, google_integration):
        """
        Generate a Folium map with markers for all locations in the itinerary and draw optimal routes.
        Returns HTML string of the map and location data.
        """
        default_lat, default_lon = 13.7563, 100.5018  # Bangkok, Thailand
        map_center = [default_lat, default_lon]
        location_data = []
        all_coordinates = []

        for location in locations:
            place_info = google_integration.get_place_by_name(location["name"])
            if place_info:
                lat, lon = place_info['latitude'], place_info['longitude']
                all_coordinates.append([lat, lon])
                image_url = google_integration.get_place_image_url(place_info['place_id'])
                location_data.append({
                    "name": place_info['name'],
                    "address": place_info['address'],
                    "lat": lat,
                    "lon": lon,
                    "is_base": location.get("is_base", False),
                    "image_url": image_url,
                    "activity": location.get("activity", ""),
                    "type": location.get("type", "general")
                })

        if len(all_coordinates) > 1:
            origin = f"{all_coordinates[0][0]},{all_coordinates[0][1]}"
            destination = f"{all_coordinates[-1][0]},{all_coordinates[-1][1]}"
            waypoints = "|".join([f"{coord[0]},{coord[1]}" for coord in all_coordinates[1:-1]])
            directions_url = (
                f"https://maps.googleapis.com/maps/api/directions/json?"
                f"origin={origin}&destination={destination}&waypoints=optimize:true|{waypoints}&key={GOOGLE_MAPS_API_KEY}"
            )
            response = requests.get(directions_url)
            if response.status_code == 200:
                data = response.json()
                if data.get("status") == "OK":
                    route = data["routes"][0]["legs"]
                    optimized_coordinates = []
                    for leg in route:
                        start_loc = leg["start_location"]
                        optimized_coordinates.append([start_loc["lat"], start_loc["lng"]])
                    all_coordinates = optimized_coordinates

        m = folium.Map(location=map_center, zoom_start=10, tiles="CartoDB positron")
        marker_cluster = MarkerCluster().add_to(m)

        icon_mapping = {
            "temple": ("fa-pagelines", "red"),
            "mountain": ("fa-mountain", "green"),
            "market": ("fa-store", "orange"),
            "hotel": ("fa-hotel", "blue"),
            "beach": ("fa-umbrella-beach", "purple"),
            "general": ("fa-info-circle", "gray")
        }

        for loc in location_data:
            # กำหนดค่า popup_html
            popup_html = f"""
            <div style="width:250px">
                <h4>{loc['name']}</h4>
                <p>{loc['address']}</p>
                <p><strong>Activity:</strong> {loc['activity']}</p>
                {f'<img src="{loc["image_url"]}" style="width:100%;max-height:150px;object-fit:cover">' if loc.get('image_url') else ''}
            </div>
            """

            # กำหนดค่า icon
            icon_details = icon_mapping.get(loc.get("type", "general"), icon_mapping["general"])
            icon = folium.Icon(color=icon_details[1], icon=icon_details[0], prefix="fa")

            # สร้าง Marker
            folium.Marker(
                location=[loc['lat'], loc['lon']],
                popup=folium.Popup(popup_html, max_width=300),
                tooltip=loc['name'],
                icon=icon
            ).add_to(marker_cluster)

        if len(all_coordinates) > 1:
            folium.PolyLine(
                locations=all_coordinates,
                color="blue",
                weight=2.5,
                opacity=1
            ).add_to(m)

        map_html = m._repr_html_()
        return map_html, location_data

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
            context = ""
            if history and len(history) > 0:
                for entry in history[-5:]:
                    if 'user' in entry:
                        context += f"User: {entry['user']}\n"
                    if 'assistant' in entry:
                        context += f"Assistant: {entry['assistant']}\n"

            prompt = f"""
            You are a Thailand travel expert with comprehensive knowledge of all provinces, tourist attractions, local culture, transportation options, and seasonal activities in Thailand. You have access to real-time data about locations, weather conditions, and travel trends.

            Your task is to plan a detailed and realistic trip itinerary based on the following:
            - {query}: The specific request or destination provided by the user.
            - {context}: Any additional preferences, interests, or constraints mentioned in the conversation (e.g., budget, duration, group type, preferred activities).

            When creating the itinerary:
            1. Ensure accuracy: Only include verified locations, attractions, and activities that exist in Thailand.
            2. Be province-specific: Clearly mention the province where each activity takes place.
            3. Consider logistics: Plan transportation between destinations realistically (e.g., driving times, flight availability).
            4. Include practical details: Suggest accommodations (hotels, resorts, guesthouses) relevant to the traveler's preferences and provide useful travel tips (e.g., best time to visit, local customs).
            5. Adapt to seasons: Tailor recommendations based on the current or expected season (e.g., rainy season vs. dry season).
            6. Format the response as follows:
            - Day 1: [Activity], [Location] ([Province]), [Time]
                - Accommodation: [Hotel/Resort Name], [Location]
                - Travel Tip: [Useful advice for the day]
            - Day 2: [Activity], [Location] ([Province]), [Time]
                - Accommodation: [Hotel/Resort Name], [Location]
                - Travel Tip: [Useful advice for the day]
            ...

            If you lack sufficient information from the query or context, ask clarifying questions before providing the itinerary.
            """
            result = subprocess.run(
                ["ollama", "run", "llama3.1:latest", prompt],
                capture_output=True,
                text=True,
                encoding='utf-8'
            )
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
        Folium map embed, place images, and hotel booking link.
        This combines information from Ollama and Google APIs.
        """
        ai_itinerary = OllamaChatbot.get_travel_plan(f"Plan a trip to {destination_name}", history)
        dest_info = GoogleIntegration.get_place_by_name(destination_name)
        if not dest_info:
            return f"I couldn't find anything about {destination_name}. Maybe try a different place?"

        locations = FoliumMapGenerator.parse_itinerary_locations(ai_itinerary, destination_name)
        google_integration = GoogleIntegration()
        folium_map_html, location_data = FoliumMapGenerator.generate_folium_map(locations, google_integration)
        main_image_url = GoogleIntegration.get_place_image_url(dest_info['place_id'])
        hotel_booking_links = GoogleIntegration.get_hotel_booking_links(destination_name)

        location_gallery_html = ""
        for loc in location_data:
            if loc.get('image_url'):
                location_gallery_html += f"""
                <div class="location-card">
                    <img src="{loc['image_url']}" alt="{loc['name']}" class="location-image"/>
                    <div class="location-info">
                        <h4>{loc['name']}</h4>
                        <p>{loc['address']}</p>
                        <p><strong>Type:</strong> {loc.get('type', 'General')}</p>
                        <p><strong>Activity:</strong> {loc['activity']}</p>
                    </div>
                </div>
                """

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
                        <!-- Add Find Hotel Button -->
                        <a href="{hotel_booking_links['Booking.com']}" target="_blank" class="book-button">Find Hotel in {destination_name}!</a>
                    </div>
                </div>
            </div>
            <div class="itinerary-section">
                <h3>Your Adventure Awaits!</h3>
                <pre class="formatted-itinerary">{ai_itinerary}</pre>
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
                .formatted-itinerary {{
                    white-space: pre-wrap;
                    word-break: break-word;
                    max-width: 100%;
                    font-size: 14px;
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
                .timestamp {{
                    font-size: 14px;
                    color: #666;
                    margin-bottom: 20px;
                }}
            </style>
        </div>
        """
        return response

# Extract text content from HTML for PDF
def extract_text_from_html(html_content):
    """
    Extract readable text content from HTML for PDF generation.
    """
    try:
        soup = BeautifulSoup(html_content, 'html.parser')
        itinerary_section = soup.select_one('.itinerary-section pre')
        if itinerary_section:
            return itinerary_section.get_text()
        return soup.get_text(separator='\n', strip=True)
    except Exception as e:
        logging.error(f"Error extracting text from HTML: {e}")
        return html_content

# Function to generate PDF from conversation history
def create_pdf_from_history(session_id, destination_name):
    """
    Generate PDF file from the conversation history.
    """
    try:
        if session_id not in conversation_history:
            return None

        pdf_filename = f"{destination_name.replace(' ', '_')}_travel_plan.pdf"
        pdf_path = os.path.join('static', pdf_filename)
        os.makedirs('static', exist_ok=True)

        c = canvas.Canvas(pdf_path, pagesize=letter)
        width, height = letter
        c.setFont("Helvetica-Bold", 16)
        c.drawString(72, height - 72, f"Travel Plan for {destination_name}")
        c.setFont("Helvetica", 10)
        c.drawString(72, height - 90, f"Generated on: {datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")

        html_content = ""
        for message in conversation_history[session_id]:
            if 'assistant' in message:
                html_content = message['assistant']
                break

        text_content = extract_text_from_html(html_content)
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

    conversation_history[session_id].append({'user': user_message})

    if "save pdf" in user_message.lower():
        destination_name = "Thailand Trip"
        pdf_path = create_pdf_from_history(session_id, destination_name)
        if pdf_path:
            emit('receive_message', {
                'message': f"Your travel plan PDF has been generated: {pdf_path}",
                'timestamp': datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            })
        else:
            emit('receive_message', {
                'message': "Sorry, there was an issue generating the PDF.",
                'timestamp': datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            })
    else:
        destination_name = user_message
        generated_details = DestinationDetailsGenerator.generate_comprehensive_details(destination_name, conversation_history[session_id])
        conversation_history[session_id].append({'assistant': generated_details})
        emit('receive_message', {
            'message': generated_details,
            'timestamp': datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        })

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
    return render_template('home.html')

@app.route('/index')
def chat_page():
    return render_template('index.html')

if __name__ == '__main__':
    socketio.run(app, debug=False)