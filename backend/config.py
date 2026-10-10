from pathlib import Path
import os

from dotenv import load_dotenv

ROOT_DIR = Path(__file__).resolve().parents[1]
CASE_DIR = ROOT_DIR / "Use Case 3"
DATA_DIR = CASE_DIR / "data"
KNOWLEDGE_DIR = CASE_DIR / "knowledge_base"
EVALUATION_DIR = CASE_DIR / "evaluation"
OUTPUT_DIR = ROOT_DIR / "outputs"
OUTPUT_DIR.mkdir(exist_ok=True)

load_dotenv(ROOT_DIR / ".env")
GROQ_API_KEY = os.getenv("GROQ_API_KEY", "").strip()
GROQ_MODEL = os.getenv("GROQ_MODEL", "openai/gpt-oss-20b")
SENTENCE_TRANSFORMER_MODEL = os.getenv(
    "SENTENCE_TRANSFORMER_MODEL", "sentence-transformers/all-MiniLM-L6-v2"
)
