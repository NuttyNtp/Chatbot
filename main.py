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
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Image
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.lib.units import inch
import json
from bs4 import BeautifulSoup
import folium
from folium.plugins import MarkerCluster
import base64
from io import BytesIO
import re
from datetime import datetime
from test import process_user_question  # Import the function from test.py

# Setup logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(message)s')
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
        # Use 'components' parameter to restrict results to Thailand
        url = f"https://maps.googleapis.com/maps/api/place/textsearch/json?query={destination_name}&components=country:TH&key={GOOGLE_MAPS_API_KEY}"
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
            else:
                logging.warning(f"No results found for '{destination_name}'.")
                return None
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

#Function to generate PDF from conversation history
def create_pdf_from_history(session_id, destination_name):
    """
    Generate a beautifully formatted PDF file from the conversation history.
    """
    try:
        if session_id not in conversation_history:
            return None

        # PDF filename
        pdf_filename = f"{destination_name.replace(' ', '_')}_travel_plan.pdf"
        pdf_path = os.path.join('static', pdf_filename)

        # Create directory if it doesn't exist
        os.makedirs('static', exist_ok=True)

        # Create PDF document
        doc = SimpleDocTemplate(pdf_path, pagesize=letter,
                                rightMargin=72, leftMargin=72,
                                topMargin=72, bottomMargin=72)
        styles = getSampleStyleSheet()
        story = []

        # Title and timestamp
        title = Paragraph(f"Travel Plan for {destination_name}", styles['Title'])
        story.append(title)
        timestamp = Paragraph(f"Generated on: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}", styles['Normal'])
        story.append(timestamp)
        story.append(Spacer(1, 12))

       # Extract text content for the PDF (latest -1 message)
        html_content = ""
        assistant_messages = [msg['assistant'] for msg in conversation_history[session_id] if 'assistant' in msg]
        if len(assistant_messages) > 1:
            html_content = assistant_messages[-2]  # ดึงข้อความก่อนหน้าข้อความล่าสุด
        elif assistant_messages:  
            html_content = assistant_messages[0]  # ถ้ามีข้อความเดียวให้ใช้ข้อความแรก


        # Convert HTML to readable text
        text_content = extract_text_from_html(html_content)

        # Split text into paragraphs
        paragraphs = text_content.split('\n')
        for paragraph in paragraphs:
            if paragraph.strip():
                p = Paragraph(paragraph.strip(), styles['BodyText'])
                story.append(p)
                story.append(Spacer(1, 12))  # Add space between paragraphs

        # Build PDF
        doc.build(story)
        return pdf_path
    except Exception as e:
        logging.error(f"Error generating PDF: {e}")
        return None

def validate_user_question(user_question):
    """
    Validate the user's question to determine if it is related to travel planning.
    """
    # Keywords to identify travel-related questions
    keywords = ["plan", "itinerary", "trip", "days", "province"]
    if not any(keyword.lower() in user_question.lower() for keyword in keywords):
        return False, "The question does not seem to be related to travel planning."

    # Check for province name
    province_match = re.search(r"(?:plan|itinerary|trip|days).*?(?:to|for) (.+?) province", user_question, re.IGNORECASE)
    if not province_match:
        return False, "Could not extract province name. Please use a format like 'Plan a trip to [province] province'."

    return True, None

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

    try:
        response = ""  # Initialize response variable

        # เงื่อนไขที่ 1: หากผู้ใช้ถามเกี่ยวกับแผนการเดินทาง
        is_travel_related, validation_error = validate_user_question(user_message)
        if is_travel_related:
            # ส่งข้อความไปยัง test.py เพื่อสร้างแผนการเดินทาง
            response = process_user_question(user_message)
            response = f"""
            <div class="destination-details-container">
                <div class="itinerary-section">
                    <h3 style="margin-bottom: 10px;">Your Travel Plan</h3>
                    <pre class="formatted-itinerary" style="white-space: pre-wrap; word-break: break-word; max-width: 100%; overflow-wrap: break-word; font-size: 14px; padding: 10px; background-color: #f9f9f9; border-radius: 8px; margin-top: 5px;">
                        {response}
                    </pre>
                </div>
            </div>
            """

        # เงื่อนไขที่ 2: หากผู้ใช้พูดถึงการขอดูรูปภาพสถานที่
        elif "show image" in user_message.lower() or "picture of" in user_message.lower():
            place_name = user_message.split("of")[-1].strip()  # ดึงชื่อสถานที่จากข้อความ
            place_info = GoogleIntegration.get_place_by_name(place_name)
            if place_info:
                place_image_url = GoogleIntegration.get_place_image_url(place_info['place_id'])
                response = f"""
                <div class="destination-details-container">
                    <div class="destination-overview">
                        <h3>{place_info['name']}</h3>
                        <p><strong>Address:</strong> {place_info['address']}</p>
                        <p><strong>Coordinates:</strong> {place_info['latitude']}, {place_info['longitude']}</p>
                        {f'<img src="{place_image_url}" alt="{place_info["name"]} Image" style="max-width: 100%; border-radius: 8px; margin-top: 10px;" />' if place_image_url else '<p>No image available.</p>'}
                    </div>
                </div>
                """
            else:
                response = f"Sorry, I couldn't find any information about {place_name}."

        # เงื่อนไขที่ 3: หากผู้ใช้ขอให้สร้างไฟล์ PDF
        elif "save pdf for my travel plan" in user_message.lower() or "create pdf" in user_message.lower() or "save pdf" in user_message.lower():
            destination_name = "Travel Plan"  # คุณสามารถปรับให้ดึงชื่อจังหวัดจากข้อความได้
            pdf_path = create_pdf_from_history(session_id, destination_name)
            if pdf_path:
                response = f"""
                <div class="pdf-download-container">
                    <p>Your travel plan has been saved as a PDF. You can download it using the link below:</p>
                    <a href="/static/{os.path.basename(pdf_path)}" target="_blank" style="color: #007BFF; text-decoration: none;">Download PDF</a>
                </div>
                """
            else:
                response = "Sorry, I couldn't generate the PDF at the moment."

        # เงื่อนไขที่ 4: หากผู้ใช้ขอลิงก์จองตั๋วเครื่องบิน
        elif "Give me a booking link of flight" in user_message.lower() or "book flight" in user_message.lower() or "flight link" in user_message.lower() or "Give me a booking link of flight" in user_message.lower():
            logging.info("Processing request for flight booking link.")
            response = """
            <div class="flight-booking-container">
                <p>You can book your flight using the following trusted platforms:</p>
                <ul>
                    <li><a href="https://www.skyscanner.com" target="_blank" style="color: #007BFF; text-decoration: none;">Skyscanner</a></li>
                    <li><a href="https://www.kayak.com" target="_blank" style="color: #007BFF; text-decoration: none;">Kayak</a></li>
                    <li><a href="https://www.expedia.com" target="_blank" style="color: #007BFF; text-decoration: none;">Expedia</a></li>
                </ul>
            </div>
            """

        # เงื่อนไขที่ 5: หากผู้ใช้ขอลิงก์จองตั๋วรถไฟ
        elif "local train" in user_message.lower() or "local train link" in user_message.lower() or "give me a booking link of local train" in user_message.lower():
            response = """
            <div class="train-booking-container">
                <p>You can book your train tickets using the following trusted platform:</p>
                <ul>
                    <li><a href="https://www.dticket.railway.co.th" target="_blank" style="color: #007BFF; text-decoration: none;">D-Ticket (State Railway of Thailand)</a></li>
                </ul>
            </div>
            """
        
        # เงื่อนไขที่ 6: หากผู้ใช้ถามคำถามทั่วไป
        else:
            prompt = f"""
            You are a Thailand Assistant with extensive knowledge about Thailand's culture, history, geography, and general information. 
            Please provide a clear, concise, and well-structured response to the user's question in no more than 3 lines for quick understanding.

            User: {user_message}
            Assistant:
            """
            result = subprocess.run(
                ["ollama", "run", "llama3.1:latest", prompt],
                capture_output=True,
                text=True,
                encoding='utf-8'
            )
            response = result.stdout.strip()

        # If no conditions match, set a default response
        if not response:
            response = "Sorry, I couldn't understand your request. Please try again."

        # ส่งข้อความกลับไปยัง UI
        logging.info(f"Response: {response}")
        conversation_history[session_id].append({'assistant': response})
        emit('receive_message', {
            'message': response,
            'timestamp': datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        })

    except Exception as e:
        logging.error(f"Error processing message: {e}")
        emit('receive_message', {
            'message': "Sorry, I couldn't process your request at the moment.",
            'timestamp': datetime.now().strftime("%Y-%m-%d %H:%M:%S")
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
    socketio.run(app, debug=False)