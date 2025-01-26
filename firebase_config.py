import os
from dotenv import load_dotenv
import requests
import json

# Load environment variables
load_dotenv()

def initialize_firebase():
    """Initialize Firebase client and return database handler"""
    try:
        # Get Firebase config from environment
        project_id = os.getenv('FIREBASE_PROJECT_ID')
        
        # Create base URL for Firebase Realtime Database
        base_url = f"https://{project_id}-default-rtdb.firebaseio.com"
        
        class FirebaseHandler:
            def __init__(self, base_url):
                self.base_url = base_url
            
            def push(self, collection, data):
                """Push data to a collection"""
                url = f"{self.base_url}/{collection}.json"
                response = requests.post(url, json=data)
                return response.json()
                
            def get(self, collection):
                """Get all data from a collection"""
                url = f"{self.base_url}/{collection}.json"
                response = requests.get(url)
                return response.json()
        
        return FirebaseHandler(base_url)
        
    except Exception as e:
        print(f"Error initializing Firebase: {e}")
        return None 