import os
from dotenv import load_dotenv
from playwright.sync_api import sync_playwright
import time

# Load environment variables
load_dotenv()

# Get Browserbase API key from environment variable
browserbase_api_key = os.getenv('BROWSERBASE_API_KEY')

def simple_browserbase_example(url):
    """
    A simple example of using Browserbase to visit a website and extract its title
    and some basic information.
    
    :param url: The URL to visit
    :return: Dictionary containing page title and meta description
    """
    with sync_playwright() as playwright:
        # Connect to Browserbase
        browser = playwright.chromium.connect_over_cdp(
            f"wss://connect.browserbase.com?apiKey={browserbase_api_key}&enableProxy=true"
        )
        
        try:
            # Create a new context and page
            context = browser.new_context()
            page = context.new_page()
            
            # Navigate to the URL
            print(f"Visiting {url}...")
            page.goto(url)
            
            # Wait for the page to load
            time.sleep(2)
            
            # Get page title
            title = page.title()
            
            # Get meta description
            meta_description = page.eval_on_selector(
                'meta[name="description"]',
                'element => element.content'
            ) if page.query_selector('meta[name="description"]') else "No description found"
            
            # Get all links on the page
            links = page.eval_on_selector_all(
                'a',
                'elements => elements.map(el => el.href)'
            )
            
            result = {
                "title": title,
                "description": meta_description,
                "number_of_links": len(links)
            }
            
            return result
            
        finally:
            # Always make sure to close everything properly
            context.close()
            browser.close()

if __name__ == "__main__":
    # Example usage
    test_url = "https://example.com"
    try:
        result = simple_browserbase_example(test_url)
        print("\nResults:")
        print(f"Page Title: {result['title']}")
        print(f"Description: {result['description']}")
        print(f"Number of links found: {result['number_of_links']}")
    except Exception as e:
        print(f"An error occurred: {str(e)}") 