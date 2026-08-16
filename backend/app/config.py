import os

from dotenv import load_dotenv

load_dotenv()


class Settings:
    deepgram_api_key: str = os.environ.get("DEEPGRAM_API_KEY", "")
    deepgram_model: str = os.environ.get("DEEPGRAM_MODEL", "nova-2")
    deepgram_language: str = os.environ.get("DEEPGRAM_LANGUAGE", "en-US")
    deepgram_sample_rate: int = int(os.environ.get("DEEPGRAM_SAMPLE_RATE", "16000"))
    frontend_origin: str = os.environ.get("FRONTEND_ORIGIN", "http://localhost:5173")


settings = Settings()
