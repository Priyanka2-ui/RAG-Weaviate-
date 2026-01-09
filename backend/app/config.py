import os
import secrets
from dotenv import load_dotenv

load_dotenv()

def _get_jwt_secret():
    jwt_secret = os.getenv("JWT_SECRET")
    if not jwt_secret:
        if os.getenv("ENVIRONMENT") == "production":
            raise ValueError("JWT_SECRET must be set in production environment")
        jwt_secret = secrets.token_urlsafe(32)
        print("WARNING: JWT_SECRET not set. Generated temporary secret for development only.")
    return jwt_secret

class Settings:
    AZURE_OPENAI_API_KEY = os.getenv("AZURE_OPENAI_KEY") or os.getenv("AZURE_OPENAI_API_KEY")
    AZURE_OPENAI_ENDPOINT = os.getenv("AZURE_OPENAI_ENDPOINT")
    AZURE_OPENAI_API_VERSION = os.getenv("AZURE_OPENAI_API_VERSION")
    AZURE_OPENAI_DEPLOYMENT_NAME = os.getenv("AZURE_OPENAI_DEPLOYMENT") or os.getenv("AZURE_OPENAI_DEPLOYMENT_NAME")
    AZURE_OPENAI_EMBEDDING_DEPLOYMENT_NAME = os.getenv("AZURE_OPENAI_EMBEDDING_DEPLOYMENT_NAME")
    
    WEAVIATE_URL = os.getenv("WEAVIATE_URL")
    WEAVIATE_API_KEY = os.getenv("WEAVIATE_API_KEY")
    SERPAPI_API_KEY = os.getenv("SERPAPI_API_KEY")
    
    JWT_SECRET = _get_jwt_secret()
    JWT_ALGO = "HS256"
    SESSION_TTL_HOURS = 24
    
    MLFLOW_TRACKING_URI = os.getenv("MLFLOW_TRACKING_URI", "file:./mlruns")
    
    DB_PATH = os.path.join(os.path.dirname(__file__), "..", "app.db")
    DATA_DB_PATH = os.path.join(os.path.dirname(__file__), "..", "data.db")
    DOCUMENTS_DIR = os.path.join(os.path.dirname(__file__), "..", "documents")

settings = Settings()

