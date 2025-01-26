import os
from dotenv import load_dotenv
import requests
import re
from playwright.sync_api import sync_playwright

# Load environment variables from .env file
load_dotenv()

# Get API keys from environment
openrouter_api_key = os.getenv('OPENROUTER_API_KEY')
browserbase_api_key = os.getenv('BROWSERBASE_API_KEY')

def listings_page(url):
    """
    Opens a webpage using Browserbase's headless browser, extracts all URLs with their link text,
    and uses OpenRouter to determine the top 3 URLs most likely to be the main listings page.

    :param url: The URL of the webpage to open.
    :return: A list of the top 3 URLs most likely to be the main listings page.
    """
    with sync_playwright() as playwright:
        # Connect to Browserbase instead of launching local browser
        browser = playwright.chromium.connect_over_cdp(
            f"wss://connect.browserbase.com?apiKey={browserbase_api_key}&enableProxy=true"
        )

        # Create a new context and page
        context = browser.new_context()
        page = context.new_page()
        
        # Navigate to URL
        page.goto(url)
        
        # Extract all URLs and their corresponding link text
        links = page.eval_on_selector_all(
            'a', 
            'elements => elements.map(element => ({ text: element.innerText.trim(), href: element.href }))'
        )
        
        # Create a dictionary with link text as keys and URLs as values
        link_dict = {link['text']: link['href'] for link in links if link['text']}
        
        # Make sure to close everything properly
        page.close()
        context.close()
        browser.close()
        
        # Use OpenRouter to determine the top 3 URLs
        headers = {
            "Authorization": f"Bearer {openrouter_api_key}",
            "Content-Type": "application/json"
        }
        data = {
            "model": "openai/gpt-4o",
            "messages": [
                {"role": "system", "content": "You are a helpful assistant."},
                {"role": "user", "content": f"Given the following links from a real estate company website, determine the top 3 URLs most likely to be the main listings page for properties SPECIFICALLY for sale. Return the result as a list of URLs only:\n\n{link_dict}"}
            ],
            "max_tokens": 150
        }
        
        response = requests.post("https://openrouter.ai/api/v1/chat/completions", headers=headers, json=data)
        response_data = response.json()
        
        # Extract the URLs from the response using regex
        response_text = response_data['choices'][0]['message']['content'].strip()
        top_urls = re.findall(r'https?://\S+', response_text)
        
        return top_urls

# Example usage:
# if __name__ == "__main__":
#     listing_urls = listings_page("https://www.linc.realty/")
#     print(listing_urls) 

