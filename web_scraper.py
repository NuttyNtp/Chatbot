import requests
from bs4 import BeautifulSoup, Tag
from typing import List, Dict
import logging
from urllib.parse import urljoin
from time import sleep
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

class TourismScraper:
    def __init__(self):
        self.base_urls = [
            'https://www.tourismthailand.org/',
            'https://www.tourismthailand.org/Attraction',
            'https://www.tourismthailand.org/Destinations',
            'https://www.tripadvisor.com/Search',
            'https://www.lonelyplanet.com/search'
        ]
        self.headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
        }
        self.session = self._create_session()

    def _create_session(self) -> requests.Session:
        session = requests.Session()
        retry_strategy = Retry(
            total=3,
            backoff_factor=1,
            status_forcelist=[429, 500, 502, 503, 504]
        )
        adapter = HTTPAdapter(max_retries=retry_strategy)
        session.mount('http://', adapter)
        session.mount('https://', adapter)
        return session

    def scrape_destination(self, destination: str) -> List[Dict[str, str]]:
        """ดึงข้อมูลเกี่ยวกับสถานที่ท่องเที่ยวจากเว็บไซต์"""
        try:
            results = []
            for base_url in self.base_urls:
                try:
                    search_url = urljoin(base_url, f'search?q={destination}')
                    logging.info(f'Scraping data from: {search_url}')
                    response = self.session.get(search_url, headers=self.headers)
                    response.raise_for_status()
                    try:
                        sleep(1)  # Rate limiting
                    except KeyboardInterrupt:
                        logging.info("Scraping interrupted by user. Saving current results...")
                        return results
                    
                    soup = BeautifulSoup(response.text, 'html.parser')
                    # ปรับ selector ตามโครงสร้าง HTML ของแต่ละเว็บไซต์
                    # Try multiple selectors for articles to handle different HTML structures
                    articles = soup.find_all(['div', 'article', 'section'], class_=['list-item', 'attraction-item', 'destination-card', 'card', 'content-item', 
                        'location-item', 'search-result', 'result-card', 'attraction-card', 'place-card']) or \
                               soup.select('.list-item, .attraction-item, .destination-card, .card, .content-item, article, .search-result, .result-card, .location-card, .place-item')
                    
                    if not articles:
                        logging.warning(f'No articles found for {destination} at {search_url}')
                        continue
                    
                    for article in articles:
                        try:
                            # Extract title from multiple possible elements
                            # Extract title with enhanced element detection
                            title_selectors = [
                                {'tag': 'h1', 'class': ['title', 'heading', 'attraction-title']},
                                {'tag': 'h2', 'class': ['title', 'heading', 'attraction-title']},
                                {'tag': 'h3', 'class': ['title', 'heading', 'attraction-title']},
                                {'class': ['title', 'heading', 'attraction-name', 'place-title']}
                            ]
                            
                            title = ''
                            for selector in title_selectors:
                                if 'tag' in selector:
                                    elem = article.find(selector['tag'], class_=selector.get('class')) if isinstance(article, Tag) else None
                                else:
                                    elem = article.find(class_=selector['class']) if isinstance(article, Tag) else None
                                if elem and elem.text:
                                    title = elem.text.strip()
                                    break
                            
                            # Extract description with enhanced element detection
                            desc_selectors = [
                                {'tag': 'p', 'class': ['description', 'excerpt', 'summary', 'content']},
                                {'class': ['description', 'excerpt', 'summary', 'content', 'attraction-description']},
                                {'tag': 'div', 'class': ['description', 'excerpt', 'summary', 'content']}
                            ]
                            
                            description = ''
                            for selector in desc_selectors:
                                if 'tag' in selector:
                                    elem = article.find(selector['tag'], class_=selector.get('class')) if isinstance(article, Tag) else None
                                else:
                                    elem = article.find(class_=selector['class']) if isinstance(article, Tag) else None
                                if elem and elem.text:
                                    description = elem.text.strip()
                                    break
                            
                            # Extract link with enhanced validation
                            link = ''
                            link_elem = article.find('a', href=True) if isinstance(article, Tag) else None
                            if isinstance(link_elem, Tag) and 'href' in link_elem.attrs:
                                link = str(link_elem['href']).strip()
                            
                            # Extract additional tourism information with enhanced detection
                            details = {}
                            info_selectors = ['details', 'info', 'metadata', 'attraction-info', 'place-details']
                            
                            for selector in info_selectors:
                                info_elem = article.find(attrs={'class': selector}) if isinstance(article, Tag) else None
                                if info_elem and isinstance(info_elem, Tag):
                                    # Extract opening hours with multiple patterns
                                    hours_patterns = ['opening hours', 'open hours', 'business hours', 'visiting hours']
                                    for pattern in hours_patterns:
                                        hours_elem = info_elem.find(text=lambda t: isinstance(t, str) and pattern in t.lower())
                                        if hours_elem and isinstance(hours_elem.parent, Tag):
                                            details['opening_hours'] = hours_elem.parent.text.strip()
                                            break
                                    
                                    # Extract admission fee with multiple patterns
                                    fee_patterns = ['admission fee', 'entrance fee', 'ticket price', 'admission price', 'entry fee']
                                    for pattern in fee_patterns:
                                        fee_elem = info_elem.find(text=lambda t: isinstance(t, str) and pattern in t.lower())
                                        if fee_elem and isinstance(fee_elem.parent, Tag):
                                            details['admission_fee'] = fee_elem.parent.text.strip()
                                            break
                                    
                                    # Extract additional details if available
                                    location_elem = info_elem.find(text=lambda t: isinstance(t, str) and 'location' in t.lower())
                                    if location_elem and isinstance(location_elem.parent, Tag):
                                        details['location'] = location_elem.parent.text.strip()
                                    
                                    contact_elem = info_elem.find(text=lambda t: isinstance(t, str) and ('contact' in t.lower() or 'phone' in t.lower()))
                                    if contact_elem and isinstance(contact_elem.parent, Tag):
                                        details['contact'] = contact_elem.parent.text.strip()
                                    
                                    break
                            
                            # Ensure we have meaningful content before adding to results
                            if title and len(title.strip()) > 0 and (description or details):
                                # Clean and validate content
                                description = description if len(description.strip()) > 0 else 'No description available.'
                                if not isinstance(details, dict):
                                    details = {}
                                # Ensure URL is properly formed
                                final_url = urljoin(base_url, link) if link else ''
                                results.append({
                                    'title': title,
                                    'description': description,
                                    'url': urljoin(base_url, link) if link else '',
                                    'details': details
                                })
                        except Exception as e:
                            logging.warning(f'Error parsing article: {str(e)} for URL: {search_url}')
                            continue
                    
                    return results
                except Exception as e:
                    logging.info("Scraping interrupted by user. Saving current results...")
                    return results
                except Exception as e:
                    logging.error(f'Error scraping destination {destination}: {str(e)}')
                    return results

    def get_destination_details(self, url: str) -> Dict[str, str]:
        """ดึงข้อมูลรายละเอียดจากหน้าเว็บของสถานที่ท่องเที่ยว"""
        try:
            logging.info(f'Fetching details from: {url}')
            response = self.session.get(url, headers=self.headers)
            response.raise_for_status()
            sleep(1)  # Rate limiting
            
            soup = BeautifulSoup(response.text, 'html.parser')
            # ปรับ selector ตามโครงสร้าง HTML ของเว็บไซต์
            content = soup.find('article')
            
            if content:
                return {
                    'content': content.get_text(strip=True),
                    'images': ','.join([str(img.get('src', '')) for img in content.find_all('img') if isinstance(img, Tag)]) if isinstance(content, Tag) else ''
                }
            return {}
        except Exception as e:
            logging.error(f'Error getting details from {url}: {str(e)}')
            return {}