"""Environment-backed settings. Mirrors the pattern in
isistasiun-be/pipeline/shared/config.py (dataclass + os.getenv + load_dotenv)."""

from __future__ import annotations

import os
from dataclasses import dataclass

from dotenv import load_dotenv

load_dotenv()


@dataclass(frozen=True)
class Settings:
    ai_backend: str = os.getenv("AI_BACKEND", "stub")
    gemini_api_key: str = os.getenv("GEMINI_API_KEY", "")
    gemini_model: str = os.getenv("GEMINI_MODEL", "gemini-3.6-flash")

    go_api_base_url: str = os.getenv("GO_API_BASE_URL", "http://localhost:8080/api/v1")
    go_api_timeout_seconds: float = float(os.getenv("GO_API_TIMEOUT_SECONDS", "5"))

    app_port: int = int(os.getenv("APP_PORT", "8000"))


settings = Settings()

# Known assumption constants (§1 isi-stasiun-ai-integration.md). AI only *reads*
# these to check claims against — it never invents or recomputes them. If BE
# changes the pipeline constant, update it here too (single source per repo).
PURCHASE_CONVERSION = 0.95  # C
V_DEFAULTS = {
    "makanan_minuman": 25000,
    "ritel_kemasan": 30000,
}
