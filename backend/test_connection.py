import os
from dotenv import load_dotenv
from pymongo import MongoClient
from pymongo.errors import ConnectionFailure, OperationFailure

# Load environment variables from .env
load_dotenv()

uri = os.getenv("MONGODB_URI")
db_name = os.getenv("MONGODB_DB", "grid_hazard_rover")

if not uri:
    print("❌ Error: MONGODB_URI not found in backend/.env!")
    exit(1)

print("⏳ Attempting to connect to MongoDB Atlas...")

try:
    # Connect to MongoDB with a 5-second timeout
    client = MongoClient(uri, serverSelectionTimeoutMS=5000)
    
    # Ping the database to verify credentials and connectivity
    client.admin.command("ping")
    print("✅ Success! Successfully connected to MongoDB Atlas.")
    print(f"📁 Target database: '{db_name}'")
except OperationFailure as e:
    print("❌ Authentication Failed: Your username or password in backend/.env is incorrect.")
    print(f"   Details: {e.details.get('errmsg', e)}")
except ConnectionFailure as e:
    print("❌ Connection Failed: Could not reach MongoDB Atlas. Check your internet connection or IP Access list.")
    print(f"   Details: {e}")
except Exception as e:
    print(f"❌ Unexpected error: {e}")
