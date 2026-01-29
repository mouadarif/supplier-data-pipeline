from __future__ import annotations
import json
import os
import pathlib
import re
from dataclasses import dataclass
from typing import Any, Dict, Optional

from google import genai
from dotenv import load_dotenv

# Load .env from project root (where this file lives)
_PROJECT_ROOT = pathlib.Path(__file__).parent.resolve()
load_dotenv(dotenv_path=_PROJECT_ROOT / ".env")


_LEGAL_SUFFIXES = [
    "SASU",
    "SAS",
    "SARL",
    "EURL",
    "SA",
    "SCI",
    "SNC",
    "SC",
    "SCA",
    "SCOP",
    "SELARL",
    "SELAFA",
    "GIE",
    "ASSOCIATION",
]


def _normalize_spaces(s: str) -> str:
    return re.sub(r"\s+", " ", s.strip())


def _upper_asciiish(s: str) -> str:
    # Keep accents as-is; DuckDB + RapidFuzz handle UTF-8 fine. Just normalize spaces & case.
    return _normalize_spaces(s).upper()


def _strip_legal_suffixes(name: str) -> str:
    s = f" {name} "
    for suf in _LEGAL_SUFFIXES:
        s = re.sub(rf"\b{re.escape(suf)}\b", " ", s, flags=re.IGNORECASE)
    return _normalize_spaces(s)


def _extract_cp(text: str) -> Optional[str]:
    m = re.search(r"\b(\d{5})\b", text or "")
    if not m:
        return None
    cp = m.group(1)
    # Basic plausibility: French CP 01000..99999
    if cp == "00000":
        return None
    return cp


@dataclass
class CleanedSupplier:
    clean_name: str
    search_token: str
    clean_cp: Optional[str]
    clean_city: Optional[str]

    def to_json(self) -> Dict[str, Any]:
        return {
            "clean_name": self.clean_name,
            "search_token": self.search_token,
            "clean_cp": self.clean_cp,
            "clean_city": self.clean_city,
        }


class LLMClient:
    """
    Minimal interface.
    - clean_supplier: produces clean_name/search token and geo fields
    - arbitrate: chooses between 2 near-ties
    """

    def clean_supplier(self, raw: Dict[str, Any]) -> CleanedSupplier:  # pragma: no cover
        raise NotImplementedError

    def arbitrate(self, question: str, a: Dict[str, Any], b: Dict[str, Any]) -> str:  # pragma: no cover
        raise NotImplementedError


class OfflineHeuristicLLM(LLMClient):
    """
    Deterministic local approximation (used for tests/offline runs).
    """

    def clean_supplier(self, raw: Dict[str, Any]) -> CleanedSupplier:
        name_raw = str(raw.get("Nom") or raw.get("name") or "")
        addr_raw = str(raw.get("Adresse 1") or raw.get("address") or "")
        city_raw = raw.get("Ville") or raw.get("city")
        cp_raw = raw.get("Postal") or raw.get("cp") or ""

        clean_name = _upper_asciiish(_strip_legal_suffixes(name_raw))

        # Search token: pick the "most distinctive" token: longest alpha token not a legal suffix
        tokens = re.findall(r"[A-Z0-9]+", clean_name)
        tokens = [t for t in tokens if t not in set(_LEGAL_SUFFIXES)]
        search_token = max(tokens, key=len) if tokens else clean_name[:20] or "UNKNOWN"

        cp = None
        if isinstance(cp_raw, (int, float)) and not (cp_raw != cp_raw):  # NaN check
            cp = f"{int(cp_raw):05d}"
        else:
            cp = _extract_cp(str(cp_raw)) or _extract_cp(addr_raw)

        city = _upper_asciiish(str(city_raw)) if city_raw and str(city_raw).strip() else None

        return CleanedSupplier(
            clean_name=clean_name,
            search_token=search_token,
            clean_cp=cp,
            clean_city=city,
        )

    def arbitrate(self, question: str, a: Dict[str, Any], b: Dict[str, Any]) -> str:
        # Simple deterministic rule: prefer head office, then shorter levenshtein distance proxy on address tokens
        if bool(a.get("is_siege")) != bool(b.get("is_siege")):
            return "A" if bool(a.get("is_siege")) else "B"
        a_addr = _upper_asciiish(str(a.get("address") or ""))
        b_addr = _upper_asciiish(str(b.get("address") or ""))
        q = _upper_asciiish(question)
        a_hits = sum(1 for t in re.findall(r"[A-Z0-9]+", q) if t in a_addr)
        b_hits = sum(1 for t in re.findall(r"[A-Z0-9]+", q) if t in b_addr)
        if a_hits != b_hits:
            return "A" if a_hits > b_hits else "B"
        return "A"


def _json_from_text(text: str) -> Dict[str, Any]:
    # Extract first JSON object from model output.
    m = re.search(r"\{.*\}", text, flags=re.DOTALL)
    if not m:
        raise ValueError("No JSON object found in LLM response")
    return json.loads(m.group(0))


class GeminiLLM(LLMClient):
    """
    Gemini-backed implementation. Requires GEMINI_API_KEY in .env.
    Includes caching to avoid redundant API calls.
    """

    def __init__(self, *, model: str = "models/gemini-2.5-flash") -> None:
        api_key = os.getenv("GEMINI_API_KEY")
        if not api_key:
            raise RuntimeError("GEMINI_API_KEY is not set in environment or .env file")
        self.client = genai.Client(api_key=api_key)
        self.model_name = model
        self._clean_cache: Dict[str, CleanedSupplier] = {}
        self._arbiter_cache: Dict[str, str] = {}

    def clean_supplier(self, raw: Dict[str, Any]) -> CleanedSupplier:
        # Cache key: combine name, address, postal for deduplication
        cache_key = (
            str(raw.get("Nom", "")) + "|" +
            str(raw.get("Adresse 1", "")) + "|" +
            str(raw.get("Postal", "")) + "|" +
            str(raw.get("Ville", ""))
        )
        
        if cache_key in self._clean_cache:
            return self._clean_cache[cache_key]
        
        prompt = (
            "You are a French business data cleaning expert.\n"
            "Task: Clean and correct this supplier record. Fix any spelling errors in company names.\n\n"
            "Return JSON with keys: clean_name, search_token, clean_cp, clean_city.\n\n"
            "Instructions:\n"
            "- clean_name: CORRECT spelling errors (e.g., 'Goggle' -> 'GOOGLE', 'Carfour' -> 'CARREFOUR'), "
            "then convert to UPPERCASE and remove legal suffixes (SAS, SARL, EURL, SA, etc.)\n"
            "- search_token: Extract the most distinctive brand/company token from clean_name "
            "(e.g., 'CARREFOUR' from 'CARREFOUR MARKET', 'GOOGLE' from 'GOOGLE FRANCE')\n"
            "- clean_cp: Extract and normalize 5-digit postal code from Postal or address fields. Set to null if invalid/missing.\n"
            "- clean_city: Correct city spelling if needed, convert to UPPERCASE. Set to null if missing.\n\n"
            f"Input: {json.dumps(raw, ensure_ascii=False, default=str)}\n\n"
            "Return ONLY the JSON object (no markdown, no explanation)."
        )
        
        try:
            response = self.client.models.generate_content(
                model=self.model_name,
                contents=prompt
            )
            data = _json_from_text(response.text)
            result = CleanedSupplier(
                clean_name=str(data.get("clean_name") or ""),
                search_token=str(data.get("search_token") or ""),
                clean_cp=(str(data.get("clean_cp")) if data.get("clean_cp") else None),
                clean_city=(str(data.get("clean_city")) if data.get("clean_city") else None),
            )
            self._clean_cache[cache_key] = result
            return result
        except Exception as e:
            # Fallback to local heuristic if LLM output fails
            print(f"[GeminiLLM] Failed to parse output, falling back to heuristic: {e}")
            result = OfflineHeuristicLLM().clean_supplier(raw)
            self._clean_cache[cache_key] = result
            return result

    def arbitrate(self, question: str, a: Dict[str, Any], b: Dict[str, Any]) -> str:
        prompt = (
            "You must choose A or B. Return JSON: {\"choice\": \"A\"} or {\"choice\": \"B\"}.\n"
            f"Question: {question}\n"
            f"A: {json.dumps(a, ensure_ascii=False, default=str)}\n"
            f"B: {json.dumps(b, ensure_ascii=False, default=str)}\n"
            "Return ONLY the JSON object."
        )
        try:
            response = self.client.models.generate_content(
                model=self.model_name,
                contents=prompt
            )
            data = _json_from_text(response.text)
            choice = str(data.get("choice", "")).upper().strip()
            return "A" if choice == "A" else "B"
        except Exception:
            return "A"

