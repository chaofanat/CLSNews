import os

SERVER_PORT = int(os.environ.get("SERVER_PORT", "8900"))
WEBHOOK_SECRET = os.environ.get("WEBHOOK_SECRET", "")

LLM_MODEL = os.environ.get("LLM_MODEL", "zai/glm-4.7-flashx")
LLM_API_KEY = os.environ.get("LLM_API_KEY", "808bec7689f0413d8d0e71ad93a15a8a.pztVOW2uwGeJcViL")
LLM_BASE_URL = os.environ.get("LLM_BASE_URL", "")

DB_PATH = os.environ.get("DB_PATH", "db/narrative.db")
MAX_RETRIES = int(os.environ.get("MAX_RETRIES", "3"))
