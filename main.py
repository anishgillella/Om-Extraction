import json
import firebase_admin
from firebase_admin import credentials, firestore
from listings_page import listings_page
from property_scraper import scrape_property_data
import os
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

def initialize_firebase():
    """Initialize Firebase with credentials from environment variables"""
    try:
        cred = credentials.Certificate(json.loads(os.getenv('FIREBASE_CREDENTIALS')))
        
        try:
            firebase_admin.delete_app(firebase_admin.get_app())
        except:
            pass
        
        firebase_admin.initialize_app(cred)
        return firestore.client()
    except Exception as e:
        print(f"\nError initializing Firebase: {str(e)}")
        return None

def setup_company_collection(db, company_url):
    """
    Create a collection for the company if it doesn't exist and maintain a list of all companies
    
    :param db: Firestore client
    :param company_url: Company's main URL
    :return: Collection reference if successful, None if failed
    """
    try:
        # Clean the URL to make it valid for a collection name
        collection_name = company_url.replace('https://', '').replace('http://', '').rstrip('/')
        
        # Check if collection exists by trying to get any document
        collection_ref = db.collection(collection_name)
        docs = collection_ref.limit(1).get()
        
        is_new_company = len(list(docs)) == 0
        
        if not is_new_company:
            print(f"\nCollection for {collection_name} already exists!")
        else:
            # Create a dummy document to ensure collection exists
            collection_ref.document('_info').set({
                'url': company_url,
                'created_at': firestore.SERVER_TIMESTAMP
            })
            print(f"\nCreated new collection for {collection_name}")
            
            # Update the companies list in the "All Companies" collection
            all_companies_ref = db.collection("All Companies").document("companies_list")
            
            # Get current list or create empty if doesn't exist
            doc = all_companies_ref.get()
            if doc.exists:
                companies = doc.to_dict().get('companies', [])
                if collection_name not in companies:
                    companies.append(collection_name)
            else:
                companies = [collection_name]
            
            # Update the document with the new list
            all_companies_ref.set({
                'companies': companies,
                'last_updated': firestore.SERVER_TIMESTAMP
            })
            print(f"Updated All Companies list with {collection_name}")
        
        return collection_ref
    except Exception as e:
        print(f"\nError setting up company collection: {str(e)}")
        return None

def store_property_data(db, main_site_url, property_data):
    """
    Store property data in Firestore under the main site's collection
    
    :param db: Firestore client
    :param main_site_url: Main website URL (collection name)
    :param property_data: Property information to store
    """
    try:
        # Clean the URL to make it valid for a collection name
        collection_name = main_site_url.replace('https://', '').replace('http://', '').rstrip('/')
        
        # Get a reference to the main site's collection
        site_collection = db.collection(collection_name)
        
        # Store each property as a document
        for property_info in property_data:
            # Create a safe document ID from the property name
            doc_id = (property_info['name']
                     .replace(' ', '_')
                     .replace('/', '_')
                     .replace('.', '_')
                     .replace(',', '')
                     .replace('(', '')
                     .replace(')', '')
                     .replace('#', '')
                     .replace('&', 'and')
                     .rstrip('_'))
            
            # Store the document
            site_collection.document(doc_id).set(property_info)
            print(f"Stored property: {property_info['name']}")
            
        return True
    except Exception as e:
        print(f"\nError storing data in Firebase: {str(e)}")
        return False

def get_all_companies(db):
    """
    Get a list of all companies in the database
    
    :param db: Firestore client
    :return: List of company dictionaries
    """
    try:
        companies = []
        all_companies_ref = db.collection("All Companies")
        docs = all_companies_ref.get()
        
        for doc in docs:
            companies.append(doc.to_dict())
            
        return companies
    except Exception as e:
        print(f"\nError getting companies list: {str(e)}")
        return []

def main():
    # Initialize Firebase
    db = initialize_firebase()
    if not db:
        print("Failed to initialize Firebase. Exiting...")
        return

    # Clear terminal and show welcome message
    print("\n" + "="*50)
    print("Real Estate Property Scraper".center(50))
    print("="*50 + "\n")

    # Step 1: Get company URL and set up collection
    company_url = input("Please enter the company's main website URL: ").strip()
    
    # Set up collection for this company
    collection_ref = setup_company_collection(db, company_url)
    if not collection_ref:
        print("Failed to set up company collection. Exiting...")
        return
        
    print("\nSearching for listings pages...")
    
    try:
        listing_urls = listings_page(company_url)
        
        print("\nTop listing pages found:")
        for i, url in enumerate(listing_urls, 1):
            print(f"{i}. {url}")
        
        print("\n" + "-"*50)
        
        # Step 2: Get specific property URLs
        print("\nPlease enter the specific property URLs you want to scrape")
        print("(comma-separated for multiple URLs):")
        property_urls = input("> ").strip()
        
        # Convert input string to list of URLs
        property_urls = [url.strip() for url in property_urls.split(",") if url.strip()]
        
        if not property_urls:
            print("\nNo valid URLs provided. Exiting...")
            return
        
        print("\nScraping property data...")
        print("-"*50)
        
        # Step 3: Scrape property data
        results = scrape_property_data(property_urls)
        
        # Step 4: Store results in Firebase
        print("\nStoring data in Firebase...")
        if store_property_data(db, company_url, results):
            print("Data successfully stored in Firebase!")
        else:
            print("Failed to store data in Firebase.")
        
        # Print results nicely formatted
        print("\nResults:")
        print(json.dumps(results, indent=2))
        
    except Exception as e:
        print(f"\nAn error occurred: {str(e)}")
        return

if __name__ == "__main__":
    main() 