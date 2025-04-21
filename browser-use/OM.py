import asyncio
import os
import re
import json
import time
import logging
from datetime import datetime
from typing import List, Dict, Optional
from browser_use import Agent, Browser, Controller, ActionResult
from langchain_openai import ChatOpenAI
from dotenv import load_dotenv
from browser_use.browser.context import BrowserContext, BrowserContextConfig

# Load environment variables
load_dotenv()

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Constants
PDF_DOWNLOAD_DIR = os.path.expanduser("~/Downloads/theus_pdfs")
MAX_PROPERTIES = 5  # Limit to 5 properties for testing

# Get API keys and configuration
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
PDF_DOWNLOAD_DIR = os.path.abspath("./browser-use/downloads")  # Absolute path to ensure consistency
HISTORY_FILE = os.path.join(PDF_DOWNLOAD_DIR, "download_history.json")

# Create download directory if it doesn't exist
os.makedirs(PDF_DOWNLOAD_DIR, exist_ok=True)
os.makedirs("logs", exist_ok=True)

print(f"Download directory created/verified at: {PDF_DOWNLOAD_DIR}")
print(f"Current contents of download directory:")
if os.path.exists(PDF_DOWNLOAD_DIR):
    files = os.listdir(PDF_DOWNLOAD_DIR)
    for f in files:
        print(f"  - {f}")
else:
    print("  (empty)")

print(f"Downloads will be stored in: {PDF_DOWNLOAD_DIR}")

def load_download_history():
    """Load previously downloaded properties to avoid duplicates"""
    if os.path.exists(HISTORY_FILE):
        try:
            with open(HISTORY_FILE, 'r') as f:
                return json.load(f)
        except (json.JSONDecodeError, IOError):
            return {"downloaded_properties": [], "property_names": []}
    return {"downloaded_properties": [], "property_names": []}

def save_download_history(history):
    """Save updated download history"""
    with open(HISTORY_FILE, 'w') as f:
        json.dump(history, f, indent=2)

def get_property_id(property_url, property_name=None):
    """Extract a unique property identifier from URL and name"""
    # Extract from URL
    url_parts = property_url.split('/')
    url_id = url_parts[-1] if len(url_parts) > 3 else url_parts[-2] if len(url_parts) > 2 else ""
    url_id = url_id.lower().strip()
    
    # Clean property name
    name_id = ""
    if property_name:
        name_id = property_name.lower().strip().replace(' ', '-')
    
    # Combine for a more unique identifier
    if name_id and url_id:
        return f"{name_id}_{url_id}"
    return url_id or name_id or property_url

# Contact information for forms
contact_info = {
    "name": "Anish Gillella",
    "email": "anish@theus.ai",
    "phone": "4690001234",
    "company": "Theus",
    "address": "123 Main St",
    "city": "San Francisco",
    "state": "CA",
    "zip": "94105",
    "broker": "Yes"  # Added broker field
}

# Create controller for custom actions
controller = Controller()

@controller.action('Fill contact form')
async def fill_contact_form(browser: Browser):
    """Fill out the contact form with our information"""
    page = await browser.get_current_page()
    try:
        # Fill in all form fields
        await page.fill('input[name="name"]', contact_info["name"])
        await page.fill('input[name="email"]', contact_info["email"])
        await page.fill('input[name="phone"]', contact_info["phone"])
        await page.fill('input[name="company"]', contact_info["company"])
        await page.fill('input[name="address"]', contact_info["address"])
        await page.fill('input[name="city"]', contact_info["city"])
        await page.fill('input[name="state"]', contact_info["state"])
        await page.fill('input[name="zip"]', contact_info["zip"])
        
        # Submit the form
        await page.click('button[type="submit"]')
        return ActionResult(extracted_content='Form filled and submitted successfully')
    except Exception as e:
        logger.error(f"Error filling form: {str(e)}")
        return ActionResult(error=str(e))

@controller.action('Download OM')
async def download_om(browser: Browser):
    """Handle the OM download process"""
    page = await browser.get_current_page()
    try:
        # Wait for download to start
        async with page.expect_download() as download_info:
            # Click the download button
            await page.click('button:has-text("Download")')
        
        # Get the download
        download = await download_info.value
        path = await download.path()
        
        # Move to our desired location
        new_path = os.path.join(PDF_DOWNLOAD_DIR, download.suggested_filename)
        os.rename(path, new_path)
        
        logger.info(f"Downloaded OM to: {new_path}")
        return ActionResult(extracted_content=f'OM downloaded to {new_path}')
    except Exception as e:
        logger.error(f"Error downloading OM: {str(e)}")
        return ActionResult(error=str(e))

async def log_step(step: dict):
    """Log each step of the process"""
    action = step.get('action', '')
    content = step.get('extracted_content', '')
    error = step.get('error', '')
    
    if error:
        logger.error(f"Step failed: {action} - Error: {error}")
    else:
        logger.info(f"Step completed: {action}")
        if content:
            logger.info(f"Result: {content}")

async def download_oms_from_listing_page(main_listing_url, contact_info, max_properties=None):
    """
    Visit each property page directly from the main listing page and download OMs immediately
    
    Args:
        main_listing_url: Main URL with all property listings
        contact_info: Dictionary with all contact information fields
        max_properties: Maximum number of properties to process (None for all)
        
    Returns:
        List of downloaded files and statistics
    """
    print(f"\nProcessing listing page: {main_listing_url}...")
    
    # Load download history to avoid duplicates
    download_history = load_download_history()
    downloaded_properties = download_history["downloaded_properties"]
    
    print(f"Found {len(downloaded_properties)} previously downloaded properties")
    
    # Initialize the LLM
    llm = ChatOpenAI(
        model="gpt-4o",
        temperature=0
    )
    
    # Configure browser context settings for downloads
    context_config = BrowserContextConfig(
        save_downloads_path=PDF_DOWNLOAD_DIR,  # Set download directory
        disable_security=True,  # Allow downloads
        wait_for_network_idle_page_load_time=2.0,  # Wait longer for downloads
        minimum_wait_page_load_time=1.0,
        browser_window_size={'width': 1280, 'height': 1100},  # Set window size
        highlight_elements=True,  # Highlight elements for better visibility
        viewport_expansion=500,  # Expand viewport for better element detection
    )
    
    # Create browser and context
    browser = Browser()  # Create browser instance
    browser_context = BrowserContext(browser=browser, config=context_config)
    
    # Create the max properties instruction
    max_properties_instruction = f"Process up to {max_properties} properties." if max_properties else "Process ALL properties."
    
    # Create agent with browser settings
    agent = Agent(
        task=f"""
        Go to the URL: {main_listing_url}

        {max_properties_instruction}

        For each property on the page:
        1. Click on the property's link to open its detail page.
        2. Look for a button or link labeled "View Package", "Download Package", or similar.
        3. Click the download button.
        4. If a form appears, use the 'Fill contact form' action to fill in the details.
        5. Use the 'Download OM' action to handle the download.
        6. Return to the listing page.

        After processing all properties on the current page, navigate to the next page (if available) and repeat until all pages are processed.

        Return a summary of which properties were successfully downloaded and which failed.
        """,
        llm=llm,
        use_vision=True,
        browser=browser,
        browser_context=browser_context,
        controller=controller,  # Add our custom controller
        save_conversation_path="logs/levy_pagination_progressive.json"
    )
    
    try:
        # Run the agent
        result = await agent.run()
        logger.info("Agent completed successfully")
        logger.info(f"Result: {result}")
        
    except Exception as e:
        logger.error(f"Error running agent: {str(e)}")
        raise
    finally:
        # Clean up browser resources
        await browser_context.close()
        await browser.close()

    # Get the final result
    result = result.final_result()
    print("Agent final result:", result)
    
    # Wait a moment for any remaining downloads to complete
    wait_time = 45  # Increased to 45 seconds for more download time
    print(f"Waiting {wait_time} seconds for downloads to complete...")
    await asyncio.sleep(wait_time)
    
    print("\nChecking for new downloads...")
    print(f"Contents of download directory after agent run:")
    if os.path.exists(PDF_DOWNLOAD_DIR):
        files = os.listdir(PDF_DOWNLOAD_DIR)
        for f in files:
            print(f"  - {f}")
    else:
        print("  (empty)")

    print("\nChecking user's Downloads folder...")
    user_downloads = os.path.expanduser("~/Downloads")
    if os.path.exists(user_downloads):
        recent_files = [f for f in os.listdir(user_downloads) 
                      if os.path.getmtime(os.path.join(user_downloads, f)) > time.time() - 7200]
        for f in recent_files:
            print(f"  - {f}")
    else:
        print("  (no access to Downloads folder)")

    # Get the updated list of files in the download directory
    current_files = set()
    if os.path.exists(PDF_DOWNLOAD_DIR):
        current_files = set(os.path.join(PDF_DOWNLOAD_DIR, f) 
                           for f in os.listdir(PDF_DOWNLOAD_DIR))
    
    # Also check in user's default Downloads folder
    user_downloads = os.path.expanduser("~/Downloads")
    if os.path.exists(user_downloads):
        # Get files modified in the last hour 
        now = time.time()  # Use time.time() instead of asyncio.get_event_loop().time()
        for filename in os.listdir(user_downloads):
            file_path = os.path.join(user_downloads, filename)
            # Check if file was modified in the last 120 minutes (2 hours)
            if os.path.getmtime(file_path) > now - 7200:  # 120 minutes = 7200 seconds
                current_files.add(file_path)
    
    # Find new files that weren't there before
    new_files = list(current_files - initial_files)
    
    # Extract property information from the result
    successful_properties = []
    failed_properties = []
    
    # Try to use regex to extract property information from the result
    property_successes = re.findall(r'(confirmed download started|successfully downloaded).*?for\s+([^.\n]+)', result.lower())
    property_failures = re.findall(r'(download failed|could not find).*?for\s+([^.\n]+)', result.lower())
    
    # Process the successful downloads (extract property name from each tuple)
    successful_properties = [match[1] for match in property_successes]
    failed_properties = [match[1] for match in property_failures]
    
    # Also look for property URLs
    property_urls = re.findall(r'https?://\S+', result)
    
    # Extract total property count if mentioned
    total_properties_match = re.search(r'processed (\d+) properties', result.lower())
    if not total_properties_match:
        total_properties_match = re.search(r'found (\d+) properties', result.lower())
    total_properties = int(total_properties_match.group(1)) if total_properties_match else len(successful_properties) + len(failed_properties)
    
    # Move files from user Downloads to our download directory and rename them
    renamed_files = []
    newly_downloaded_properties = []
    newly_downloaded_names = []
    
    for file_path in new_files:
        # Copy file to our download directory if it's in user Downloads
        if not file_path.startswith(PDF_DOWNLOAD_DIR):
            filename = os.path.basename(file_path)
            new_path = os.path.join(PDF_DOWNLOAD_DIR, filename)
            try:
                import shutil
                shutil.copy2(file_path, new_path)
                print(f"Copied file from {file_path} to {new_path}")
                file_path = new_path
            except Exception as e:
                print(f"Warning: Could not copy file - {str(e)}")
        
        # Rename the file to include property identifiers
        filename = os.path.basename(file_path)
        
        # Extract property name if possible
        property_name = None
        if successful_properties and len(new_files) == len(successful_properties):
            property_name = successful_properties[new_files.index(file_path)]
        elif successful_properties and len(successful_properties) == 1:
            property_name = successful_properties[0]
        
        # Add a prefix based on property name
        prefix = f"{property_name}_" if property_name else ""
        new_filename = f"OM_Levy_{prefix}{filename}"
        new_path = os.path.join(PDF_DOWNLOAD_DIR, new_filename)
        
        try:
            os.rename(file_path, new_path)
            renamed_files.append(new_path)
            
            # Get property ID for tracking
            if property_name:
                property_id = get_property_id(new_path, property_name)
                newly_downloaded_properties.append(property_id)
                newly_downloaded_names.append(property_name)
                
        except Exception as e:
            print(f"Warning: Could not rename file - {str(e)}")
            renamed_files.append(file_path)
    
    # Update download history to prevent future duplicates
    download_history = load_download_history()
    downloaded_properties = download_history["downloaded_properties"]
    property_names = download_history["property_names"]
    
    # Add newly downloaded properties to history
    downloaded_properties.extend(newly_downloaded_properties)
    property_names.extend(newly_downloaded_names)
    download_history["downloaded_properties"] = downloaded_properties
    download_history["property_names"] = property_names
    save_download_history(download_history)
    
    return {
        'downloaded_files': renamed_files,
        'successful_properties': successful_properties,
        'failed_properties': failed_properties,
        'property_urls': property_urls,
        'result_summary': result,
        'total_properties': total_properties,
        'newly_downloaded': newly_downloaded_names
    }

async def main():
    """Main function to run the Levy Retail OM Downloader with Progressive Processing"""
    print(f"=== Levy Retail Group OM Downloader with Progressive Processing ===")
    print(f"This script will process properties as they appear, downloading OMs and closing PDF tabs")
    print(f"All downloads will be stored in: {PDF_DOWNLOAD_DIR}")
    
    # Get user input
    main_listing_url = input("Enter the Levy Retail URL with property listings: ")
    if not main_listing_url:
        main_listing_url = "https://www.levyretail.com/multi-tenant-properties/"
    
    # For Levy Retail, we'll need comprehensive contact information for download forms
    print("\nContact information for download forms:")
    print("(This will be used to fill out forms when downloading Offering Memorandums)")
    
    # Ask if user wants to process all properties or just a subset
    process_all = input("\nProcess ALL properties? (y/n): ").lower()
    max_properties = None
    if process_all != 'y':
        try:
            max_properties = int(input("How many properties to process? "))
        except ValueError:
            print("Invalid input. Processing all properties.")
    
    try:
        # Process the listing page and download OMs immediately
        result = await download_oms_from_listing_page(
            main_listing_url, contact_info, max_properties
        )
        
        # Show summary results
        print("\n=== Download Summary ===")
        
        # Display the downloaded files
        if result['downloaded_files']:
            print(f"\nSuccessfully downloaded {len(result['downloaded_files'])} NEW PDF files:")
            for file in result['downloaded_files']:
                print(f" - {os.path.basename(file)}")
            print(f"\nFiles saved to: {os.path.abspath(PDF_DOWNLOAD_DIR)}")
        else:
            print("No NEW PDF files were downloaded.")
        
        # Display the agent's summary result
        print("\nAgent's detailed summary:")
        print(result['result_summary'])
        
        # Check if all properties were processed
        total_handled = len(result['newly_downloaded']) + len(result['failed_properties'])
        if result['total_properties'] > total_handled:
            print(f"\nWARNING: Not all properties were processed. {result['total_properties'] - total_handled} properties were neither downloaded nor reported as failed.")
            print("Consider running the script again to process the remaining properties.")
        
    except Exception as e:
        print(f"\nAn error occurred: {str(e)}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    # Run the main function
    asyncio.run(main()) 