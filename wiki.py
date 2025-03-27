# from langchain_community.tools import WikipediaQueryRun
# from langchain_community.utilities import WikipediaAPIWrapper
# GOOGLE_MAPS_API_KEY = "AIzaSyDv_OEg50nhbpvW-EtNy3ze-dqsG4tPEEI"
# # from test import WikipediaIntegration
# # # wikipedia = WikipediaQueryRun(api_wrapper=WikipediaAPIWrapper())
# # # a = wikipedia.run("Page: Category:Tourist attractions in Chiang Mai")
# # # print(a)

# # # Initialize the WikipediaIntegration class
# # wikipedia_integration = WikipediaIntegration()

# # # Test input with 'Chiang Mai'
# # attractions = wikipedia_integration.get_tourist_attractions("Chiang Mai")

# # # Print the result
# # print(attractions)

# import logging
# import requests

# # Wikipedia Integration Class
# class WikipediaIntegration:
#     def __init__(self):
#         self.wikipedia = WikipediaQueryRun(api_wrapper=WikipediaAPIWrapper())

#     def get_tourist_attractions(self, province_name):
#         """
#         Fetch tourist attractions from Wikipedia for a given province.
#         """
#         queries = [
#             f"Page: Category:Tourist attractions in {province_name}",
#             f"Category:Tourist attractions in {province_name} province",
#             f"{province_name} province attractions",
#             f"Things to do in {province_name} province",
#             f"Pages in category Buddhist temples in {province_name} province",
#             f"Pages in category Tourist attractions in {province_name} province",
#             f"Pages in category Museums in {province_name}",
#             f"{province_name}",
#             f"Tourism in {province_name}",  # Direct search for tourism-related page
#             f"{province_name} tourism",
#             f"{province_name} attractions",
#             f"Page: Category:Tourist attractions in {province_name}"
#         ]
#         relevant_attractions = []
#         for query in queries:
#             logging.info(f"Querying Wikipedia with: {query}")
#             attractions = self.wikipedia.run(query)
#             logging.info(f"Attractions found: {attractions}")

#             # กรองข้อมูลที่เกี่ยวข้องกับจังหวัดที่ระบุ
#             for attraction in attractions.split("\n"):
#                 if province_name.lower() in attraction.lower():
#                     relevant_attractions.append(attraction)

#             if relevant_attractions:
#                 break  # หากพบข้อมูลที่เกี่ยวข้อง ให้หยุดการค้นหา

#         if not relevant_attractions:
#             logging.warning(f"No relevant attractions found for {province_name}.")
#             return []

#         return relevant_attractions


# # Google Integration Class
# class GoogleIntegration:
#     queried_places = set()

#     @staticmethod
#     def get_place_by_name(destination_name):
#         """
#         Search for a place by name using Google Places API.
#         """
#         url = f"https://maps.googleapis.com/maps/api/place/textsearch/json?query={destination_name}&components=country:TH&key={GOOGLE_MAPS_API_KEY}"
#         logging.info(f"Querying Google Places API with: {destination_name}")
#         response = requests.get(url)
#         if response.status_code == 200:
#             data = response.json()
#             logging.info(f"Google API Response: {data}")
#             if 'results' in data and len(data['results']) > 0:
#                 place = data['results'][0]
#                 logging.info(f"Place found: {place}")
#                 return {
#                     'name': place.get('name'),
#                     'address': place.get('formatted_address', 'No address available'),
#                     'latitude': place['geometry']['location']['lat'],
#                     'longitude': place['geometry']['location']['lng'],
#                     'place_id': place['place_id']
#                 }
#             else:
#                 logging.warning(f"No results found for '{destination_name}'.")
#                 return None
#         logging.error(f"Google API request failed with status code {response.status_code}.")
#         return None


# # Usage Example:
# # 1. Get tourist attractions for Chiang Mai from Wikipedia
# wikipedia_integration = WikipediaIntegration()
# attractions = wikipedia_integration.get_tourist_attractions("Bangkok")

# # 2. For each attraction, use Google Integration to fetch place details
# google_integration = GoogleIntegration()

# place_details = []
# for attraction in attractions:
#     place = google_integration.get_place_by_name(attraction)
#     if place:
#         place_details.append(place)

# # Print the place details
# for place in place_details:
#     print(f"Name: {place['name']}, Address: {place['address']}, Latitude: {place['latitude']}, Longitude: {place['longitude']}")

import logging
import re
from langchain.prompts import ChatPromptTemplate
from langchain.chains import LLMChain
from langchain_ollama.llms import OllamaLLM

class ItineraryGenerator:
    def __init__(self):
        self.model = OllamaLLM(model="llama3.1")
        
        self.prompt_template = ChatPromptTemplate.from_template(
            """Question: {question}\nProvince: {province}\nAnswer: Provide a list of tourist attractions' names in {province} province, Thailand."""
        )
        
        # ใช้ LLMChain ตามปกติ
        self.chain = LLMChain(llm=self.model, prompt=self.prompt_template)

    def extract_trip_details(self, input_text):
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

        question = f"Create a {days} days itinerary for {province} province based on the following tourist attractions: {filtered_attractions}."
        logging.info(f"Generated question for Llama: {question}")

        # ใช้ invoke() แทน run() และใส่ province ด้วย
        response = self.chain.invoke({"question": question, "province": province})  
        logging.info(f"Response from Llama: {response}")
        return response

# ตัวอย่างการทดสอบ
itinerary_generator = ItineraryGenerator()
attractions = ["Wat Phra That Doi Suthep Thailand", "Railay Beach Thailand", "Phuket Old Town Thailand"]
result = itinerary_generator.generate_itinerary("Create a 3 days itinerary for Chiang Mai province", attractions)
print(result)
