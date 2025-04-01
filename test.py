import time
import requests
import logging
import re
from langchain_ollama.llms import OllamaLLM
from langchain.chains import LLMChain
from langchain_core.prompts import ChatPromptTemplate
from langchain_community.tools import WikipediaQueryRun
from langchain_community.utilities import WikipediaAPIWrapper
import folium
from folium.plugins import MarkerCluster
from typing import Optional, List, Dict
import random

# Constants
GOOGLE_MAPS_API_KEY = "AIzaSyDv_OEg50nhbpvW-EtNy3ze-dqsG4tPEEI"

# Logging Configuration
logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(message)s")

# Google Integration Class
class GoogleIntegration:
    queried_places = set()

    @staticmethod
    def get_place_by_name(destination_name):
        """
        Search for a place by name using Google Places API.
        """
        url = f"https://maps.googleapis.com/maps/api/place/textsearch/json?query={destination_name}&components=country:TH&key={GOOGLE_MAPS_API_KEY}"
        logging.info(f"Querying Google Places API with: {destination_name}")
        response = requests.get(url)
        if response.status_code == 200:
            data = response.json()
            logging.info(f"Google API Response: {data}")
            if 'results' in data and len(data['results']) > 0:
                place = data['results'][0]
                logging.info(f"Place found: {place}")
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
        logging.error(f"Google API request failed with status code {response.status_code}.")
        return None

    @staticmethod
    def get_place_image_url(place_id):
        """
        Fetch an image URL from Google Places API using the place_id.
        """
        url = f"https://maps.googleapis.com/maps/api/place/details/json?placeid={place_id}&key={GOOGLE_MAPS_API_KEY}"
        logging.info(f"Fetching image for place_id: {place_id}")
        response = requests.get(url)
        if response.status_code == 200:
            data = response.json()
            logging.info(f"Google API Response for place_id {place_id}: {data}")
            if 'result' in data and 'photos' in data['result']:
                photo_reference = data['result']['photos'][0]['photo_reference']
                image_url = f"https://maps.googleapis.com/maps/api/place/photo?maxwidth=800&photoreference={photo_reference}&key={GOOGLE_MAPS_API_KEY}"
                logging.info(f"Image URL: {image_url}")
                return image_url
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

    @staticmethod
    def get_places_by_itinerary(itinerary_places):
        """
        Search for multiple places by names from the itinerary using Google Places API.
        """
        places = []
        for place_name in itinerary_places:
            logging.info(f"Searching for place: {place_name}")
            place_info = GoogleIntegration.get_place_by_name(place_name)
            if place_info:
                places.append({
                    "name": place_info["name"],
                    "address": place_info["address"],
                    "latitude": place_info["latitude"],
                    "longitude": place_info["longitude"],
                    "place_id": place_info["place_id"]
                })
            else:
                logging.warning(f"Could not find details for place: {place_name}")
        return places

# Wikipedia Integration Class
class WikipediaIntegration:
    def __init__(self):
        self.wikipedia = WikipediaQueryRun(api_wrapper=WikipediaAPIWrapper())

    def get_tourist_attractions(self, province_name):
        """
        Fetch tourist attractions from Wikipedia for a given province.
        """
        queries = [
            f"Page: Category:Tourist attractions in {province_name}",
            f"Category:Tourist attractions in {province_name} province",
            f"{province_name} province attractions",
            f"Things to do in {province_name} province",
            f"Pages in category Buddhist temples in {province_name} province",
            f"Pages in category Tourist attractions in {province_name} province",
            f"Pages in category Museums in {province_name}",
            f"{province_name}",
            f"Tourism in {province_name}",  # Direct search for tourism-related page
            f"{province_name} tourism",
            f"{province_name} attractions",
            f"Page: Category:Tourist attractions in {province_name}"
        ]
        relevant_attractions = []
        for query in queries:
            logging.info(f"Querying Wikipedia with: {query}")
            attractions = self.wikipedia.run(query)
            logging.info(f"Attractions found: {attractions}")

            # กรองข้อมูลที่เกี่ยวข้องกับจังหวัดที่ระบุ
            for attraction in attractions.split("\n"):
                if province_name.lower() in attraction.lower():
                    relevant_attractions.append(attraction)

            if relevant_attractions:
                break  # หากพบข้อมูลที่เกี่ยวข้อง ให้หยุดการค้นหา

        if not relevant_attractions:
            logging.warning(f"No relevant attractions found for {province_name}.")
            return []

        return relevant_attractions

class ItineraryGenerator:
    def __init__(self):
        self.model = OllamaLLM(model="llama3.1")
        
        self.prompt_template = ChatPromptTemplate.from_template(
            """Question: {question}\nProvince: {province}\nAnswer: Provide a list of tourist attractions' names in {province} province, Thailand."""
        )
        
        # ใช้ LLMChain ตามปกติ
        self.chain = LLMChain(llm=self.model, prompt=self.prompt_template)

    def extract_trip_details(self, input_text):
        if not isinstance(input_text, str):
            logging.error("Input text is not a string.")
            return None, None

        match = re.search(r"(an?\s+)?(\d+)\s+day[s]?\s+itinerary\s+for\s+([a-zA-Z\s]+)\s+province", input_text)
        if not match:
            match = re.search(r"itinerary\s+for\s+([a-zA-Z\s]+)\s+province", input_text)
            if match:
                days = 3
                province = match.group(1).strip()
                return days, province
            else:
                logging.warning(f"ไม่สามารถแยกข้อมูลจากข้อความ: {input_text}")
                return None, None

        days = int(match.group(2))
        province = match.group(3).strip()
        return days, province

    def generate_itinerary(self, input_text, attractions):
        days, province = self.extract_trip_details(input_text)
        if not days or not province:
            return "ไม่สามารถแยกข้อมูลจากข้อความได้"

        filtered_attractions = [attraction for attraction in attractions if province.lower() in attraction.lower()]

        if not filtered_attractions:
            return f"ไม่พบสถานที่ท่องเที่ยวที่สามารถค้นหาบน Google Maps ในจังหวัด {province}."

        question = f"""
Create a {days}-day travel itinerary for {province} province in Thailand.
The itinerary should include:
1. A list of activities for each day.
2. Highlight 2-3 famous tourist attractions for each day from the following list: {filtered_attractions}.
3. Ensure the plan is well-structured with proper formatting, including line breaks and bullet points.
4. For each tourist attraction, make sure to mention the specific name of the place clearly.
"""
        logging.info(f"Generated question for Llama: {question}")

        # ใช้ invoke() แทน run() และใส่ province ด้วย
        response = self.chain.invoke({"question": question, "province": province})
        logging.info(f"Raw response from Llama: {response}")

        # ตรวจสอบว่า response เป็น dict หรือไม่
        if isinstance(response, dict):
            if "answer" in response:
                response = response["answer"]
            elif "text" in response:  # รองรับคีย์ "text"
                response = response["text"]
            else:
                logging.error("Response from Llama does not contain 'answer' or 'text' key.")
                return "เกิดข้อผิดพลาดในการประมวลผลคำตอบจาก Llama."

        # ตรวจสอบว่า response เป็น string หรือไม่
        if not isinstance(response, str):
            logging.error(f"Expected string, but got {type(response)}: {response}")
            return "เกิดข้อผิดพลาดในการประมวลผลคำตอบจาก Llama."

        logging.info(f"Processed response from Llama: {response}")
        return response

# Enhanced Folium Map Integration 
class EnhancedFoliumMapGenerator:
    @staticmethod
    def parse_itinerary_by_day(itinerary_text, base_location_name):
        """
        Parse itinerary text to extract location names and activities, grouped by day.
        Returns a dictionary with day numbers as keys and lists of locations as values.
        """
        day_locations = {}
        
        # Define patterns to match different types of places
        place_patterns = {
            "temple": r"(?:วัด|[Tt]emple|Wat)\s*([\w\s]+)",
            "mountain": r"(?:ภูเขา|[Mm]ountain|Khao)\s*([\w\s]+)",
            "market": r"(?:ตลาด|[Mm]arket)\s*([\w\s]+)",
            "beach": r"(?:ชายหาด|[Bb]each|Hat)\s*([\w\s]+)",
            "waterfall": r"(?:[Ww]aterfall|น้ำตก)\s*([\w\s]+)",
            "park": r"(?:[Pp]ark|อุทยาน|[Nn]ational [Pp]ark)\s*([\w\s]+)",
            "museum": r"(?:[Mm]useum|พิพิธภัณฑ์)\s*([\w\s]+)",
            "island": r"(?:[Ii]sland|เกาะ|Ko)\s*([\w\s]+)",
            "cave": r"(?:[Cc]ave|ถ้ำ|Tham)\s*([\w\s]+)",
            "palace": r"(?:[Pp]alace|พระราชวัง)\s*([\w\s]+)",
            "general": r"(?:visit|at|to|explore)\s+([\w\s]+)"
        }
        
        # Excluded keywords to filter out non-places
        excluded_keywords = ["nightclub", "club", "office", "agency", "tour", "company"]
        
        # Extract days from itinerary using regex
        day_pattern = r'Day (\d+):(.+?)(?=Day \d+:|$)'
        day_matches = re.findall(day_pattern, itinerary_text, re.DOTALL)
        
        # Base location is added to day 1
        base_location = {
            "name": f"{base_location_name} province",
            "is_base": True,
            "activity": f"Main Destination: {base_location_name} province",
            "day": 1
        }
        
        # Process each day's content
        for day_num, day_content in day_matches:
            day_num = int(day_num)
            day_locations[day_num] = []
            
            # Process lines for this day
            activity_lines = [line.strip() for line in day_content.split('\n') if line.strip()]
            for line in activity_lines:
                for place_type, pattern in place_patterns.items():
                    matches = re.finditer(pattern, line, re.IGNORECASE)
                    for match in matches:
                        location_name = match.group(1).strip()
                        if location_name and not any(keyword in location_name.lower() for keyword in excluded_keywords):
                            # Clean up location name and combine with province
                            clean_location = location_name.strip('.,:;()')
                            if clean_location and len(clean_location) > 2:  # Minimum 3 characters for a place name
                                full_name = f"{clean_location}, {base_location_name}"
                                # Check if it's already in the list for this day
                                if not any(loc["name"] == full_name for loc in day_locations.get(day_num, [])):
                                    day_locations.setdefault(day_num, []).append({
                                        "name": full_name,
                                        "type": place_type,
                                        "activity": line,
                                        "is_base": False,
                                        "day": day_num
                                    })
        
        # Add base location to day 1 if we have days
        if day_locations and 1 in day_locations:
            day_locations[1].insert(0, base_location)
        
        # Ensure we have all days represented
        max_day = max(day_locations.keys()) if day_locations else 0
        for day in range(1, max_day + 1):
            if day not in day_locations:
                day_locations[day] = []
        
        return day_locations

    @staticmethod
    def generate_folium_map(day_locations, google_integration):
        """
        Generate a Folium map with day-by-day routes and color-coded markers.
        Returns HTML string of the map and location data.
        """
        default_lat, default_lon = 13.7563, 100.5018  # Bangkok, Thailand
        map_center = [default_lat, default_lon]
        all_location_data = []
        image_cache = {}  # Cache for images
        # Day colors for routes and markers
        day_colors = ['blue', 'red', 'green', 'purple', 'orange', 'darkblue', 'darkred', 'darkgreen', 
                    'cadetblue', 'darkpurple', 'pink', 'lightblue', 'lightgreen', 'gray', 'black']
        # Create the map
        m = folium.Map(location=map_center, zoom_start=10, tiles="CartoDB positron")
        # Create a separate FeatureGroup for each day
        feature_groups = {}
        # First pass: Get coordinates for all locations
        flat_locations = []
        for day, locations in day_locations.items():
            for location in locations:
                location["day"] = day  # Ensure day is set
                flat_locations.append(location)
        # Get coordinates and image URLs for all locations
        for day, locations in day_locations.items():
            day_color = day_colors[(day - 1) % len(day_colors)]
            if day not in feature_groups:
                feature_groups[day] = folium.FeatureGroup(name=f"Day {day}")
                feature_groups[day].add_to(m)

            for idx, location in enumerate(locations):
                place_info = google_integration.get_place_by_name(location["name"])
                if place_info:
                    lat, lon = place_info['latitude'], place_info['longitude']
                    # Cache image URL
                    place_id = place_info['place_id']
                    if place_id not in image_cache:
                        image_url = google_integration.get_place_image_url(place_id)
                        image_cache[place_id] = image_url
                    else:
                        image_url = image_cache[place_id]
                    # Store location data
                    location_data = {
                        "name": place_info['name'],
                        "address": place_info['address'],
                        "lat": lat,
                        "lon": lon,
                        "is_base": location.get("is_base", False),
                        "image_url": image_url,
                        "activity": location.get("activity", ""),
                        "type": location.get("type", "general"),
                        "day": day
                    }
                    all_location_data.append(location_data)

                    # Add marker with number
                    popup_html = f"""
                    <div style="width:250px">
                        <h4>{place_info['name']}</h4>
                        <p><strong>Day {day}</strong></p>
                        <p>{place_info['address']}</p>
                        <p><strong>Activity:</strong> {location['activity']}</p>
                        {f'<img src="{image_url}" style="width:100%;max-height:150px;object-fit:cover">' if image_url else ''}
                    </div>
                    """
                    # Create a DivIcon with the number
                    number_icon = folium.DivIcon(
                        html=f"""
                        <div style="background-color: {day_color}; border-radius: 50%; width: 30px; height: 30px; text-align: center; line-height: 30px; color: white; font-weight: bold;">
                            {idx + 1}
                        </div>
                        """
                    )
                    folium.Marker(
                        location=[lat, lon],
                        popup=folium.Popup(popup_html, max_width=300),
                        tooltip=f"Day {day}: {place_info['name']}",
                        icon=number_icon
                    ).add_to(feature_groups[day])

        # Draw routes for each day
        for day, locations in day_locations.items():
            coordinates = [[loc["lat"], loc["lon"]] for loc in all_location_data if loc["day"] == day]
            if len(coordinates) > 1:
                day_color = day_colors[(day - 1) % len(day_colors)]
                folium.PolyLine(
                    locations=coordinates,
                    color=day_color,
                    weight=4,
                    opacity=0.8,
                    tooltip=f"Day {day} Route"
                ).add_to(feature_groups[day])

        # Add Layer Control to toggle visibility of days
        folium.LayerControl().add_to(m)
        # If we have coordinates, set map center to the first valid location
        if all_location_data:
            map_center = [all_location_data[0]['lat'], all_location_data[0]['lon']]
            m.location = map_center
        map_html = m._repr_html_()
        return map_html, all_location_data

# Main Functionality
def process_user_question(user_question):
    """
    Process the user's question and generate a summarized travel itinerary with hotel links, images, and an interactive map.
    """
    # ตรวจสอบความถูกต้องของคำถามผู้ใช้
    province_match = re.search(
        r"(?:plan|itinerary|trip|days).*?(?:to|for) (.+?) province",
        user_question,
        re.IGNORECASE
    )
    if not province_match:
        logging.error("Could not extract province name. Please use a format like 'Plan a trip to [province] province'.")
        return "กรุณาระบุจังหวัดในประเทศไทยที่ต้องการวางแผนการเดินทาง."

    province_name = province_match.group(1).strip()
    logging.info(f"Searching for tourist attractions in {province_name} province...")

    # ตรวจสอบจำนวนวันในคำถามผู้ใช้
    days_match = re.search(r"(\d+)\s*(?:day|days)", user_question, re.IGNORECASE)
    if not days_match:
        logging.warning("Could not extract the number of days. Defaulting to 3 days.")
        num_days = 3  # Default to 3 days if not specified
    else:
        num_days = int(days_match.group(1))
        logging.info(f"Number of days specified: {num_days}")

    # ดึงข้อมูลสถานที่ท่องเที่ยวจาก Wikipedia
    wikipedia_integration = WikipediaIntegration()
    attractions = wikipedia_integration.get_tourist_attractions(province_name)

    if not attractions:
        logging.warning(f"No information found for tourist attractions in {province_name} province.")
        return f"ไม่มีข้อมูลสถานที่ท่องเที่ยวสำหรับจังหวัด {province_name}."

    # Generate travel itinerary
    itinerary_generator = ItineraryGenerator()
    itinerary = itinerary_generator.generate_itinerary(user_question, attractions)
    logging.info(f"Generated Itinerary: {itinerary}")

    # Clean and format the itinerary text
    itinerary_cleaned = re.sub(r"[*#/]", "", itinerary).strip()

    # ดึง filtered_attractions จาก ItineraryGenerator
    filtered_attractions = [attraction for attraction in attractions if province_name.lower() in attraction.lower()]

    # Parse locations from the itinerary by day
    enhanced_map_generator = EnhancedFoliumMapGenerator()
    day_locations = enhanced_map_generator.parse_itinerary_by_day(itinerary, province_name)
    
    # Generate Google integration
    google_integration = GoogleIntegration()
    
    # Generate the enhanced map with day-by-day routes
    map_html, location_data = enhanced_map_generator.generate_folium_map(day_locations, google_integration)

    # Fetch hotel booking links
    booking_links = google_integration.generate_booking_links(province_name)
    filtered_booking_links = [
        hotel for hotel in booking_links if hotel['website'] != "No website available"
    ][:5]  # Limit to 5 hotels with available links

    # Group images by day for the gallery
    day_images = {}
    for loc in location_data:
        day = loc.get('day', 0)
        if day not in day_images:
            day_images[day] = []
        
        if loc.get('image_url') and province_name.lower() in loc.get('address', '').lower():
            day_images[day].append(loc)
    
    # Create a day-by-day gallery of images
    location_gallery_html = "<h3>Day-by-Day Attractions:</h3>"
    for day in sorted(day_images.keys()):
        if day_images[day]:
            location_gallery_html += f"<h4>Day {day} Locations:</h4>"
            location_gallery_html += "<div style='display: grid; grid-template-columns: repeat(auto-fill, minmax(200px, 1fr)); gap: 15px;'>"
            
            # Get unique locations for this day
            seen_names = set()
            for loc in day_images[day]:
                if loc['name'] not in seen_names:
                    seen_names.add(loc['name'])
                    location_gallery_html += f"""
                    <div style="border: 1px solid #ddd; border-radius: 8px; overflow: hidden; text-align: center;">
                        <img src="{loc['image_url']}" alt="{loc['name']}" style="width:100%;height:150px;object-fit:cover;">
                        <div style="padding: 10px;">
                            <h4 style="font-size: 16px;">{loc['name']}</h4>
                            <p style="font-size: 14px; color: gray;">{loc['address']}</p>
                            <p style="font-size: 12px;"><strong>Activity:</strong> {loc['activity']}</p>
                        </div>
                    </div>
                    """
            location_gallery_html += "</div>"

    # Combine all parts into the response
    response = f"""
    <div style="font-family: Arial, sans-serif; padding: 20px;">
        <h2 style="color: #333;">Travel Itinerary for {province_name}</h2>
        <div style="background-color: #f9f9f9; padding: 15px; border-radius: 8px;">
            <pre class="formatted-itinerary" style="white-space: pre-wrap; line-height: 1.6; font-size: 14px; color: #555;">
{itinerary_cleaned}
            </pre>
        </div>
        <h3 style="margin-top: 20px;">Interactive Map with Daily Routes:</h3>
        <div>
{map_html}
        </div>
        <h3 style="margin-top: 20px;">Hotel Booking Links:</h3>
        <ul style="list-style-type: none; padding: 0;">
            {''.join([
                f"<li style='margin: 5px 0;'><a href='{hotel['website']}' target='_blank' style='text-decoration: none; color: #007BFF;'>{hotel['name']}</a></li>"
                for hotel in filtered_booking_links
            ])}
        </ul>
        {location_gallery_html}
    </div>
    """
    return response

# Entry Point
if __name__ == "__main__":
    user_question = input("Please enter your question (e.g., 'Create a travel itinerary for Krabi province'): ")
    start_time = time.time()
    result = process_user_question(user_question)
    print(result)
    end_time = time.time()
    logging.info(f"Processing Time: {end_time - start_time:.2f} seconds")