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
    logging.info(f"Generated Itinerary: {itinerary}")

    # Initialize GoogleIntegration instance
    google_integration = GoogleIntegration()

    # Fetch hotel booking links
    booking_links = google_integration.generate_booking_links(province_name)
    logging.info("Hotel Booking Links:")
    for hotel in booking_links:
        logging.info(f"Hotel: {hotel['name']}, Website: {hotel['website']}")

    # Parse locations from the itinerary
    folium_map_generator = FoliumMapGenerator()
    locations = folium_map_generator.parse_itinerary_locations(itinerary, province_name)
    logging.info(f"Parsed Locations: {locations}")

    # Generate Folium map
    map_html, location_data = folium_map_generator.generate_folium_map(locations, google_integration)
    logging.info("Generated Folium map and location data.")
    logging.info(f"Location Data: {location_data}")

    # Add images to the response
    location_gallery_html = "<h3>Recommended Locations:</h3><div class='gallery-container'>"
    for loc in location_data:
        if loc.get("image_url"):
            location_gallery_html += f"""
            <div class="location-card">
                <img src="{loc['image_url']}" alt="{loc['name']}" class="location-image" style="width:100%;height:150px;object-fit:cover;border-radius:8px;"/>
                <div class="location-info">
                    <h4>{loc['name']}</h4>
                    <p>{loc['address']}</p>
                    <p><strong>Activity:</strong> {loc['activity']}</p>
                </div>
            </div>
            """
    location_gallery_html += "</div>"

    # Combine all parts into the response
    response = f"""
    <h2>Travel Itinerary for {province_name}</h2>
    <pre class="formatted-itinerary">{itinerary}</pre>
    <h3>Interactive Map:</h3>
    <div>{map_html}</div>
    <h3>Hotel Booking Links:</h3>
    <ul>
        {''.join([f"<li><a href='{hotel['website']}' target='_blank'>{hotel['name']}</a></li>" for hotel in booking_links])}
    </ul>
    {location_gallery_html}
    """
    return response

# Entry Point
if __name__ == "__main__":
    user_question = input("Please enter your question (e.g., 'Create a travel itinerary for Krabi province'): ")
    start_time = time.time()
    process_user_question(user_question)
    end_time = time.time()
    logging.info(f"Processing Time: {end_time - start_time:.2f} seconds")

# def validate_user_question(question: str):
#     # Define pattern for provinces in English
#     province_pattern = r"(Chiang Mai|Bangkok|Phuket|Krabi|Chiang Rai|Saraburi|Udon Thani|Surat Thani|Nakhon Ratchasima|Amnat Charoen|Ang Thong|Buriram|Chachoengsao|Chai Nat|Chaiyaphum|Chanthaburi|Chonburi|Chumphon|Kalasin|Kamphaeng Phet|Kanchanaburi|Khon Kaen|Krabi|Lampang|Lamphun|Loei|Lopburi|Mae Hong Son|Maha Sarakham|Mukdahan|Nakhon Nayok|Nakhon Pathom|Nakhon Phanom|Nakhon Sawan|Nakhon Si Thammarat|Nan|Narathiwat|Nong Bua Lamphu|Nong Khai|Nonthaburi|Pathum Thani|Phang Nga|Phayao|Phetchabun|Phetchaburi|Phichit|Phitsanulok|Phra Nakhon Si Ayutthaya|Phrae|Prachinburi|Prachuap Khiri Khan|Ranong|Ratchaburi|Rayong|Samut Sakhon|Sa Kaeo|Sakon Nakhon|Samut Prakan|Samut Songkhram|Satun|Sisaket|Songkhla|Sukhothai|Suphan Buri|Surat Thani|Surin|Tak|Trang|Trat|Ubon Ratchathani|Udon Thani|Uthai Thani|Uttaradit|Yala|Yasothon)"
    
#     # Define pattern for number of days or nights
#     days_pattern = r"(\d+)\s*(days|nights)"  # Match 'days' or 'nights'

#     # Extract the number of days from the question
#     days_match = re.search(days_pattern, question)
#     if days_match:
#         days = int(days_match.group(1))  # Extract the number of days from the question
#     else:
#         days = None  # If no number of days is found

#     # Extract the province from the question
#     province_match = re.search(province_pattern, question)
#     if province_match:
#         province = province_match.group(1)  # Extract the province name
#     else:
#         province = None  # If no province is found

#     # Check if both province and days are found
#     if province and days:
#         return province, days
#     else:
#         return None, None


# def process_user_question(user_question):
#     """
#     ประมวลผลคำถามของผู้ใช้และสร้างแผนการเดินทาง
#     """
#     # ตรวจสอบความถูกต้องของคำถามผู้ใช้
#     province, days = validate_user_question(user_question)
#     if not province or not days:
#         return "<p>กรุณาระบุจังหวัดและจำนวนวันที่ต้องการวางแผนการเดินทาง.</p>"

#     logging.info(f"ค้นหาสถานที่ท่องเที่ยวในจังหวัด {province} สำหรับ {days} วัน...")

#     # ดึงข้อมูลสถานที่ท่องเที่ยวจาก Wikipedia
#     wikipedia_integration = WikipediaIntegration()
#     attractions = wikipedia_integration.get_tourist_attractions(province)
#     logging.info(f"Attractions for {province}: {attractions}")
#     if not attractions:
#         return f"<p>ไม่มีข้อมูลสถานที่ท่องเที่ยวสำหรับจังหวัด {province}. กรุณาลองจังหวัดอื่น.</p>"

#     # สร้างแผนการเดินทาง
#     itinerary_generator = ItineraryGenerator()
#     itinerary = itinerary_generator.generate_itinerary(province, attractions)
#     logging.info(f"Generated itinerary: {itinerary}")
#     if not itinerary:
#         return f"<p>ไม่สามารถสร้างแผนการเดินทางได้ กรุณาลองอีกครั้ง.</p>"

#     # แยกสถานที่จากแผนการเดินทาง
#     folium_map_generator = FoliumMapGenerator()
#     locations = folium_map_generator.parse_itinerary_locations(itinerary, province)

#     # ตรวจสอบสถานที่เพื่อให้แน่ใจว่าอยู่ในประเทศไทย
#     valid_locations = []
#     google_integration = GoogleIntegration()
#     for loc in locations:
#         place_info = google_integration.get_place_by_name(loc["name"])
#         if place_info and "Thailand" in place_info["address"]:
#             valid_locations.append({
#                 "name": place_info["name"],
#                 "address": place_info["address"],
#                 "latitude": place_info["latitude"],
#                 "longitude": place_info["longitude"],
#                 "activity": loc["activity"],
#                 "type": loc.get("type", "general"),
#                 "image_url": google_integration.get_place_image_url(place_info["place_id"])
#             })

#     # สร้างแผนที่ Folium จากสถานที่ที่ตรวจสอบแล้ว
#     map_html, location_data = folium_map_generator.generate_folium_map(valid_locations, google_integration)

#     # ดึงลิงก์การจองโรงแรม
#     hotel_links = google_integration.generate_booking_links(province)
#     hotel_links_html = "<h3>ลิงก์การจองโรงแรม:</h3><ul>"
#     for hotel in hotel_links:
#         hotel_links_html += f"<li><a href='{hotel['website']}' target='_blank'>{hotel['name']}</a></li>"
#     hotel_links_html += "</ul>"

#     # สร้าง HTML แกลเลอรีสถานที่จากสถานที่ที่ตรวจสอบแล้ว
#     location_gallery_html = "<h3>สถานที่แนะนำ:</h3><div>"
#     for loc in location_data:
#         if loc.get("image_url"):
#             location_gallery_html += f"""
#             <div>
#                 <img src="{loc['image_url']}" alt="{loc['name']}" style="width:100px;height:100px;object-fit:cover;"/>
#                 <p>{loc['name']}</p>
#             </div>
#             """
#     location_gallery_html += "</div>"

#     # รวมทุกส่วนเป็นคำตอบเดียว
#     response = f"""
#     <h2>แผนการเดินทางสำหรับจังหวัด {province}</h2>
#     <pre class="formatted-itinerary">{itinerary}</pre>
#     <h3>แผนที่แบบโต้ตอบ:</h3>
#     <div>{map_html}</div>
#     {hotel_links_html}
#     {location_gallery_html}
#     """
#     return response

# # Entry Point
# if __name__ == "__main__":
#     user_question = input("Please enter your question (e.g., 'Create a travel itinerary for Krabi province'): ")
#     start_time = time.time()
#     process_user_question(user_question)
#     end_time = time.time()
#     logging.info(f"Processing Time: {end_time - start_time:.2f} seconds")