import time
import requests
import logging
import re
from langchain_core.prompts import ChatPromptTemplate
from langchain_ollama.llms import OllamaLLM
from langchain_community.tools import WikipediaQueryRun
from langchain_community.utilities import WikipediaAPIWrapper
import folium
from folium.plugins import MarkerCluster
# Constants
GOOGLE_MAPS_API_KEY = "AIzaSyDv_OEg50nhbpvW-EtNy3ze-dqsG4tPEEI"

# Logging Configuration
logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s: %(message)s")

# Google Integration Class
class GoogleIntegration:
    queried_places = set()

    @staticmethod
    def get_place_by_name(destination_name):
        """
        Search for a place by name using Google Places API.
        """
        if destination_name in GoogleIntegration.queried_places:
            logging.info(f"Skipping {destination_name}, already processed.")
            return None

        url = f"https://maps.googleapis.com/maps/api/place/textsearch/json?query={destination_name}&components=country:TH&key={GOOGLE_MAPS_API_KEY}"
        response = requests.get(url)
        if response.status_code == 200:
            data = response.json()
            if 'results' in data and len(data['results']) > 0:
                place = data['results'][0]
                GoogleIntegration.queried_places.add(destination_name)
                return {
                    'name': place.get('name'),
                    'address': place.get('formatted_address', 'No address available'),
                    'latitude': place['geometry']['location']['lat'],
                    'longitude': place['geometry']['location']['lng'],
                    'place_id': place['place_id']
                }
            else:
                logging.warning(f"No results found for '{destination_name}'.")
                return None
        logging.error("Google API request failed or no results found.")
        return None

    @staticmethod
    def get_place_image_url(place_id):
        """
        Fetch an image URL from Google Places API using the place_id.
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
    def generate_booking_links(province_name):
        """
        Generate direct booking links for hotels in the given province.
        """
        base_url = f"https://maps.googleapis.com/maps/api/place/textsearch/json"
        query = f"hotels in {province_name} province"
        params = {
            "query": query,
            "key": GOOGLE_MAPS_API_KEY
        }
        response = requests.get(base_url, params=params)
        if response.status_code == 200:
            data = response.json()
            if 'results' in data and len(data['results']) > 0:
                hotels = []
                for hotel in data['results']:
                    hotel_name = hotel.get('name', 'Unknown Hotel')
                    website = None
                    if 'place_id' in hotel:
                        # Fetch details for each hotel to get the website
                        details_url = f"https://maps.googleapis.com/maps/api/place/details/json"
                        details_params = {
                            "place_id": hotel['place_id'],
                            "fields": "name,website",
                            "key": GOOGLE_MAPS_API_KEY
                        }
                        details_response = requests.get(details_url, params=details_params)
                        if details_response.status_code == 200:
                            details_data = details_response.json()
                            website = details_data.get('result', {}).get('website')
                    hotels.append({
                        "name": hotel_name,
                        "website": website or "No website available"
                    })
                return hotels
        logging.error("Failed to fetch hotel booking links.")
        return []

# Wikipedia Integration Class
class WikipediaIntegration:
    def __init__(self):
        self.wikipedia = WikipediaQueryRun(api_wrapper=WikipediaAPIWrapper())

    def get_tourist_attractions(self, province_name):
        """
        Fetch tourist attractions from Wikipedia for a given province.
        """
        query = f"Tourist attractions in {province_name} province"
        return self.wikipedia.run(query)

# Itinerary Generator Class
class ItineraryGenerator:
    def __init__(self):
        self.model = OllamaLLM(model="llama3.1")
        self.prompt_template = ChatPromptTemplate.from_template(
            """Question: {question}\n\nAnswer: Let's think step by step."""
        )

    def generate_itinerary(self, province_name, attractions):
        """
        Generate a travel itinerary using the model.
        """
        question = f"Create a travel itinerary for {province_name} province based on these tourist attractions: {attractions}."
        return self.model.invoke(f"Question: {question}\nAnswer: Let's think step by step.")
    
# Folium Map Integration 
class FoliumMapGenerator:
    @staticmethod
    def parse_itinerary_locations(itinerary_text, base_location_name):
        """
        Parse itinerary text to extract location names and activities.
        Returns a list of dictionaries with location details.
        """
        locations = []
        # Add the main destination as the first location
        locations.append({"name": base_location_name, "is_base": True, "activity": f"Main Destination: {base_location_name}"})
        
        # Define patterns to match different types of places
        place_patterns = {
            "temple": r"(?:วัด|temple)\s*([\w\s]+)",
            "mountain": r"(?:ภูเขา|mountain)\s*([\w\s]+)",
            "market": r"(?:ตลาด|market)\s*([\w\s]+)",
            "beach": r"(?:ชายหาด|beach)\s*([\w\s]+)",
            "general": r"at\s+([\w\s]+)"
        }
        
        # Keywords to exclude unwanted places
        excluded_keywords = ["nightclub", "club", "office", "agency", "tour", "company"]
        
        # Extract locations from itinerary using regex
        day_pattern = r'Day \d+:.*?(?=Day \d+:|$)'
        day_matches = re.findall(day_pattern, itinerary_text, re.DOTALL)
        for day_match in day_matches:
            activity_lines = [line.strip() for line in day_match.split('\n') if line.strip()]
            daily_locations = []
            for line in activity_lines:
                matched = False
                for place_type, pattern in place_patterns.items():
                    match = re.search(pattern, line, re.IGNORECASE)
                    if match:
                        location_name = match.group(1).strip()
                        if location_name and location_name != base_location_name:
                            # Exclude unwanted places
                            if not any(keyword in location_name.lower() for keyword in excluded_keywords):
                                if len(daily_locations) < 4:  # Limit to 4 locations per day
                                    daily_locations.append({
                                        "name": f"{location_name}, {base_location_name}",
                                        "type": place_type,
                                        "activity": line,
                                        "is_base": False
                                    })
                                matched = True
                                break
                if not matched:
                    # If no specific type matches, try general extraction
                    general_match = re.search(place_patterns["general"], line, re.IGNORECASE)
                    if general_match:
                        location_name = general_match.group(1).strip()
                        if location_name and location_name != base_location_name:
                            # Exclude unwanted places
                            if not any(keyword in location_name.lower() for keyword in excluded_keywords):
                                if len(daily_locations) < 4:  # Limit to 4 locations per day
                                    daily_locations.append({
                                        "name": f"{location_name}, {base_location_name}",
                                        "type": "general",
                                        "activity": line,
                                        "is_base": False
                                    })
            locations.extend(daily_locations)
        
        # Remove duplicates while preserving order
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
        image_cache = {}  # Cache images to avoid duplicates
        
        # Fetch coordinates and images for each location
        for location in locations:
            place_info = google_integration.get_place_by_name(location["name"])
            if place_info:
                lat, lon = place_info['latitude'], place_info['longitude']
                all_coordinates.append([lat, lon])
                
                # Fetch image URL and cache it to avoid duplicates
                place_id = place_info['place_id']
                if place_id not in image_cache:
                    image_url = google_integration.get_place_image_url(place_id)
                    image_cache[place_id] = image_url
                else:
                    image_url = image_cache[place_id]
                
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
        
        # Create base map
        m = folium.Map(location=map_center, zoom_start=10, tiles="CartoDB positron")
        marker_cluster = MarkerCluster().add_to(m)
        
        # Define icons for different location types
        icon_mapping = {
            "temple": ("fa-pagelines", "red"),
            "mountain": ("fa-mountain", "green"),
            "market": ("fa-store", "orange"),
            "beach": ("fa-umbrella-beach", "purple"),
            "general": ("fa-info-circle", "gray")
        }
        
        # Add markers for each location
        for loc in location_data:
            # Exclude business-related locations
            if loc["type"] not in ["hotel", "general"] or "tour" not in loc["name"].lower():
                popup_html = f"""
                <div style="width:250px">
                    <h4>{loc['name']}</h4>
                    <p>{loc['address']}</p>
                    <p><strong>Activity:</strong> {loc['activity']}</p>
                    {f'<img src="{loc["image_url"]}" style="width:100%;max-height:150px;object-fit:cover">' if loc.get('image_url') else ''}
                </div>
                """
                icon_type = loc.get("type", "general")
                icon_details = icon_mapping.get(icon_type, icon_mapping["general"])
                icon = folium.Icon(color=icon_details[1], icon=icon_details[0], prefix="fa")
                folium.Marker(
                    location=[loc['lat'], loc['lon']],
                    popup=folium.Popup(popup_html, max_width=300),
                    tooltip=loc['name'],
                    icon=icon
                ).add_to(marker_cluster)
        
        # Draw lines between locations
        if len(all_coordinates) > 1:
            folium.PolyLine(
                locations=all_coordinates,
                color="blue",
                weight=2.5,
                opacity=1
            ).add_to(m)
        
        map_html = m._repr_html_()
        return map_html, location_data

# Main Functionality
def process_user_question(user_question):
    """
    Process the user's question and generate a travel itinerary.
    """
    # ตรวจสอบคำสำคัญในคำถาม
    keywords = ["plan", "itinerary", "trip", "days", "province"]
    if not any(keyword.lower() in user_question.lower() for keyword in keywords):
        logging.error("The question does not seem to be related to travel planning. Please include keywords like 'plan', 'itinerary', 'trip', or 'days'.")
        return

    # ใช้ Regular Expression ที่ยืดหยุ่นขึ้น
    province_match = re.search(
        r"(?:plan|itinerary|trip|days).*?(?:to|for) (.+?) province",
        user_question,
        re.IGNORECASE
    )
    if not province_match:
        logging.error("Could not extract province name. Please use a format like 'Plan a trip to [province] province' or 'Itinerary for [province] province'.")
        return

    province_name = province_match.group(1).strip()
    logging.info(f"Searching for tourist attractions in {province_name} province...")

    # Fetch tourist attractions from Wikipedia
    wikipedia_integration = WikipediaIntegration()
    attractions = wikipedia_integration.get_tourist_attractions(province_name)

    if not attractions:
        logging.warning(f"No information found for tourist attractions in {province_name} province.")
        return

    # Generate travel itinerary
    itinerary_generator = ItineraryGenerator()
    itinerary = itinerary_generator.generate_itinerary(province_name, attractions)

    # แสดงผลลิงก์โรงแรม
    booking_links = google_integration.generate_booking_links(province_name)
    logging.info("Hotel Booking Links:")
    for hotel in booking_links:
        logging.info(f"Hotel: {hotel['name']}, Website: {hotel['website']}")
        
    # Parse locations from the itinerary
    folium_map_generator = FoliumMapGenerator()
    locations = folium_map_generator.parse_itinerary_locations(itinerary, province_name)

    # Generate Folium map
    google_integration = GoogleIntegration()
    map_html, location_data = folium_map_generator.generate_folium_map(locations, google_integration)

    # แสดงผลแผนการเดินทาง
    logging.info(f"Generated Itinerary:\n{itinerary}")

    # แสดงผลแผนที่ Folium
    with open("map.html", "w", encoding="utf-8") as f:
        f.write(map_html)
    logging.info("Map has been saved as 'map.html'. Open this file in your browser to view the map.")

# Entry Point
if __name__ == "__main__":
    user_question = input("Please enter your question (e.g., 'Create a travel itinerary for Krabi province'): ")
    start_time = time.time()
    process_user_question(user_question)
    end_time = time.time()
    logging.info(f"Processing Time: {end_time - start_time:.2f} seconds")