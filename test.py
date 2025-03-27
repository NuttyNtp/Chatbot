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
from typing import Optional
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

    # Parse locations from the itinerary
    folium_map_generator = FoliumMapGenerator()
    itinerary_places = [loc["name"] for loc in folium_map_generator.parse_itinerary_locations(itinerary, province_name)]

    # ค้นหาข้อมูลสถานที่จาก Google Places API
    google_integration = GoogleIntegration()
    valid_locations = google_integration.get_places_by_itinerary(itinerary_places)

    # ตรวจสอบข้อมูลที่ได้
    for location in valid_locations:
        logging.info(f"Place found: {location['name']} at {location['address']}")

    # Generate Folium map
    folium_map_generator = FoliumMapGenerator()
    map_html, location_data = folium_map_generator.generate_folium_map(valid_locations, google_integration)

    # Fetch hotel booking links
    booking_links = google_integration.generate_booking_links(province_name)
    filtered_booking_links = [
        hotel for hotel in booking_links if hotel['website'] != "No website available"
    ][:5]  # Limit to 5 hotels with available links

    # Ensure map images are unique and coordinates are within the specified province
    unique_location_data = []
    seen_images = set()
    for loc in location_data:
        if loc.get("image_url") not in seen_images and province_name.lower() in loc["address"].lower():
            unique_location_data.append(loc)
            seen_images.add(loc.get("image_url"))

    # Add images to the response
    location_gallery_html = "<h3>Recommended Locations:</h3><div style='display: grid; grid-template-columns: repeat(auto-fill, minmax(200px, 1fr)); gap: 15px;'>"
    for loc in unique_location_data:
        if loc.get("image_url"):
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
        <h3 style="margin-top: 20px;">Interactive Map:</h3>
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
    process_user_question(user_question)
    end_time = time.time()
    logging.info(f"Processing Time: {end_time - start_time:.2f} seconds")
