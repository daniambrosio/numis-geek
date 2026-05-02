from dotenv import load_dotenv
import os

load_dotenv()

DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///./numis_geek.db")
SECRET_KEY = os.getenv("SECRET_KEY", "change-me-in-production")
SYSADMIN_PASSWORD = os.getenv("SYSADMIN_PASSWORD", "changeme123")
