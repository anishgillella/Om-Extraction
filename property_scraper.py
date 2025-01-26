import os
from dotenv import load_dotenv
from playwright.sync_api import sync_playwright
from playwright.sync_api import TimeoutError as PlaywrightTimeoutError
import requests
import re
import time
import json
from firebase_config import initialize_firebase
from datetime import datetime

# Load environment variables from .env file
load_dotenv()

# Get API keys from environment
openrouter_api_key = os.getenv('OPENROUTER_API_KEY')
browserbase_api_key = os.getenv('BROWSERBASE_API_KEY')

def clean_url(url):
    """Clean URL by removing any unwanted characters like backticks and quotes"""
    return url.strip().rstrip('`\'"')

def scrape_property_data(urls, company_url):
    """
    Scrapes property data and stores it in Firebase using Browserbase for browser automation.
    
    :param urls: A list of URLs of the webpages to scrape
    :param company_url: The main company website URL
    :return: A dictionary with flattened property information including url and images
    """
    results = []
    
    # Initialize Firebase
    db = initialize_firebase()
    if not db:
        raise Exception("Failed to initialize Firebase")
    
    try:
        with sync_playwright() as playwright:
            # Connect to Browserbase with proxy enabled for better scraping
            browser = playwright.chromium.connect_over_cdp(
                f"wss://connect.browserbase.com?apiKey={browserbase_api_key}&enableProxy=true"
            )
            
            # Create a new context
            context = browser.new_context()
            
            for url in urls:
                page = context.new_page()
                
                try:
                    page.goto(url, timeout=20000)  # Set a timeout of 20 seconds
                except PlaywrightTimeoutError:
                    error_info = {
                        "url": url,
                        "company_url": company_url,
                        "name": "",
                        "address": "",
                        "price": "",
                        "details": "Page load timed out",
                        "images": []
                    }
                    results.append(error_info)
                    continue
                except Exception as e:
                    error_info = {
                        "url": url,
                        "company_url": company_url,
                        "name": "",
                        "address": "",
                        "price": "",
                        "details": f"An error occurred: {e}",
                        "images": []
                    }
                    results.append(error_info)
                    continue

                # Wait for 2 seconds to ensure the page is loaded
                time.sleep(2)

                # Scroll to the bottom of the page
                page.evaluate('window.scrollTo(0, document.body.scrollHeight)')
                time.sleep(2)  # Wait for 2 seconds

                # Scroll back to the top of the page
                page.evaluate('window.scrollTo(0, 0)')
                time.sleep(2)  # Wait for 2 seconds

                # Assuming header and footer are defined by common HTML tags or classes
                page_content = page.evaluate('''
                    () => {
                        const header = document.querySelector('header');
                        const footer = document.querySelector('footer');
                        
                        if (header) header.remove();
                        if (footer) footer.remove();
                        
                        return document.body.innerText.trim();
                    }
                ''')

                # Clean image URLs when extracting them
                images = page.eval_on_selector_all('img', '''
                    imgs => imgs.map(img => ({
                        src: img.src.trim(),
                        alt: img.alt
                    }))
                ''')
                unique_images = {clean_url(img['src']): img['alt'] for img in images}

                page.close()

                # Use OpenRouter to filter out relevant property information
                headers = {
                    "Authorization": f"Bearer {openrouter_api_key}",
                    "Content-Type": "application/json"
                }
                data = {
                    "model": "openai/gpt-4o",
                    "messages": [
                        {"role": "system", "content": "You are a helpful assistant."},
                        {"role": "user", "content": f"Extract as much relevant property information as possible from the following text and return it as a JSON object with the fields 'name', 'address', 'price', and 'details'. The 'price' field should contain the price of the property or 'Not Given' if not available. The 'details' field should be a single text field containing all relevant information such as total area, construction details, availability, transaction type, and any other relevant property information. Ensure the response is a valid JSON object:\n\n{page_content}"}
                    ],
                    "max_tokens": 300
                }
                
                response = requests.post("https://openrouter.ai/api/v1/chat/completions", headers=headers, json=data)
                response_data = response.json()
                
                # Extract the JSON object from the response
                if 'choices' in response_data and response_data['choices']:
                    raw_content = response_data['choices'][0]['message']['content'].strip()
                    
                    try:
                        # Directly parse the JSON if possible
                        property_info = json.loads(raw_content)
                    except json.JSONDecodeError:
                        # Fallback to regex if direct parsing fails
                        json_match = re.search(r'\{.*?\}', raw_content, re.DOTALL)
                        if json_match:
                            try:
                                property_info = json.loads(json_match.group(0))
                            except json.JSONDecodeError:
                                property_info = {"error": "Invalid JSON format"}
                        else:
                            property_info = {"error": "No JSON found"}
                else:
                    property_info = {"error": "No valid response from API"}

                # Send image URLs to OpenAI to determine which are related to the property
                image_data = {
                    "model": "openai/gpt-4o",
                    "messages": [
                        {"role": "system", "content": "You are a helpful assistant."},
                        {"role": "user", "content": f"From the following image URLs and their descriptions, choose as many images as you deem even slightly relevant to the property. It's fine if some don't turn out very relevant; it's more important to capture all potential property-related images:\n\n{unique_images}"}
                    ],
                    "max_tokens": 150
                }
                
                image_response = requests.post("https://openrouter.ai/api/v1/chat/completions", headers=headers, json=image_data)
                image_response_data = image_response.json()
                
                # Clean the relevant image URLs
                if 'choices' in image_response_data and image_response_data['choices']:
                    relevant_images_text = image_response_data['choices'][0]['message']['content'].strip()
                    relevant_images = [clean_url(url) for url in re.findall(r'https?://\S+', relevant_images_text)]
                else:
                    relevant_images = []

                # Create flattened property info with additional metadata
                flattened_info = {
                    "url": url,
                    "company_url": company_url,
                    "name": property_info.get("name") if property_info.get("name") else "Not Available",
                    "address": property_info.get("address") if property_info.get("address") else "Not Available",
                    "price": property_info.get("price") if property_info.get("price") else "Not Available",
                    "details": property_info.get("details") if property_info.get("details") else "Not Available",
                    "images": relevant_images if relevant_images else [],
                    "created_at": datetime.now().isoformat(),
                    "updated_at": datetime.now().isoformat()
                }
                
                # Handle case where property_info contains an error
                if "error" in property_info:
                    flattened_info.update({
                        "name": "Not Available",
                        "address": "Not Available",
                        "price": "Not Available",
                        "details": property_info["error"]
                    })
                
                # Store in Firebase
                try:
                    db.push('properties', flattened_info)
                except Exception as e:
                    print(f"Error storing property in Firebase: {e}")

                results.append(flattened_info)

            # Make sure to close everything properly
            context.close()
            browser.close()

    except Exception as e:
        error_info = {
            "url": urls[0],
            "company_url": company_url,
            "name": "",
            "address": "",
            "price": "",
            "details": f"An error occurred: {str(e)}",
            "images": []
        }
        return [error_info]

    return results

# Example usage:
# urls = [
#     "https://tx-cre.com/100-lupita-circle-del-rio-tx-78840-for-sale-or-for-lease/",
#     "https://tx-cre.com/1-chaparral-hill-drive-for-sale/"
# ]
# results = scrape_property_data(urls, "https://tx-cre.com")
# print(json.dumps(results, indent=2))