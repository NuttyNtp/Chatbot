import time
import requests
import logging
import re
from langchain_core.prompts import ChatPromptTemplate
from langchain_ollama.llms import OllamaLLM
from langchain_community.tools import WikipediaQueryRun
from langchain_community.utilities import WikipediaAPIWrapper

# Constants
GOOGLE_MAPS_API_KEY =  "AIzaSyDv_OEg50nhbpvW-EtNy3ze-dqsG4tPEEI"

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
        question = f"Create a travel itinerary for {province_name} province based on these tourist attractions: {attractions}"
        return self.model.invoke(f"Question: {question}\nAnswer: Let's think step by step.")

# Main Functionality
def process_user_question(user_question):
    """
    Process the user's question and generate a travel itinerary.
    """
    # ตรวจสอบคำสำคัญในคำถาม
    keywords = ["travel", "itinerary", "trip", "plan", "province"]
    if not any(keyword in user_question.lower() for keyword in keywords):
        logging.error("The question does not seem to be related to travel planning. Please include keywords like 'travel', 'itinerary', or 'trip'.")
        return

    # ใช้ Regular Expression ที่ยืดหยุ่นขึ้น
    province_match = re.search(r"(?:travel itinerary|trip|plan).*for (.+?) province", user_question, re.IGNORECASE)
    if not province_match:
        logging.error("Could not extract province name. Please use a format like 'Create a travel itinerary for [province] province'.")
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
    logging.info(f"Generated Itinerary:\n{itinerary}")

    # Process places in the itinerary
    places_in_plan = re.findall(r"\b([A-Za-z0-9\s]+(?:Park|Sanctuary|Waterfall|Mountain|Temple|City|Lake|National))\b", itinerary)
    google_integration = GoogleIntegration()

    for place_name in places_in_plan:
        place_info = google_integration.get_place_by_name(place_name)
        if place_info:
            logging.info(f"Place info for {place_name}: {place_info}")
            image_url = google_integration.get_place_image_url(place_info['place_id'])
            if image_url:
                logging.info(f"Place image URL for {place_name}: {image_url}")
            else:
                logging.warning(f"Could not find an image for {place_name}.")
        else:
            logging.warning(f"Could not find place information for {place_name}.")

# Entry Point
if __name__ == "__main__":
    user_question = input("Please enter your question (e.g., 'Create a travel itinerary for Krabi province'): ")
    start_time = time.time()
    process_user_question(user_question)
    end_time = time.time()
    logging.info(f"Processing Time: {end_time - start_time:.2f} seconds")