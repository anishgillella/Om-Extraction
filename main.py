import json
from listings_page import listings_page
from property_scraper import scrape_property_data
import os
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

def main():
    # Clear terminal and show welcome message
    print("\n" + "="*50)
    print("Real Estate Property Scraper".center(50))
    print("="*50 + "\n")

    # Step 1: Get company URL
    company_url = input("Please enter the company's main website URL: ").strip()
    
    print("\nSearching for listings pages...")
    
    try:
        listing_urls = listings_page(company_url)
        
        print("\nTop listing pages found:")
        for i, url in enumerate(listing_urls, 1):
            print(f"{i}. {url}")
        
        print("\n" + "-"*50)
        
        # Step 2: Get specific property URLs
        print("\nPlease enter the URLs of the properties you want to scrape (comma-separated):")
        property_urls = input("> ").strip()
        
        # Convert input string to list of URLs
        property_urls = [url.strip() for url in property_urls.split(",") if url.strip()]
        
        if not property_urls:
            print("\nNo valid URLs provided. Exiting...")
            return
        
        print("\nScraping property data...")
        print("-"*50)
        
        # Pass company_url to scrape_property_data
        results = scrape_property_data(property_urls, company_url)
        
        print("\nResults:")
        print(json.dumps(results, indent=2))
        
    except Exception as e:
        print(f"\nAn error occurred: {str(e)}")
        return

if __name__ == "__main__":
    main() 