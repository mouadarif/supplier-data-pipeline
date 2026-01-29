"""
Google Search provider for non-French suppliers.
Uses Gemini API with web search capability to find company information.
"""
from __future__ import annotations

import json
import os
from dataclasses import dataclass
from typing import Any, Dict, Optional

from dotenv import load_dotenv

load_dotenv()

try:
    from google import genai
    HAS_GEMINI = True
except ImportError:
    HAS_GEMINI = False


@dataclass
class GoogleSearchResult:
    """Result from Google search for a supplier."""
    input_id: str
    company_name: str
    country: str
    city: Optional[str]
    postal_code: Optional[str]
    found_website: Optional[str]
    found_address: Optional[str]
    found_phone: Optional[str]
    found_email: Optional[str]
    confidence_score: float  # 0.0 to 1.0
    search_method: str
    raw_data: Dict[str, Any]


class GoogleSearchProvider:
    """
    Search provider for non-French suppliers using Gemini API with web search.
    """
    
    def __init__(self, model_name: str = "models/gemini-2.5-flash"):
        if not HAS_GEMINI:
            raise ImportError("google-genai package not installed. Install with: pip install google-genai")
        
        api_key = os.getenv("GEMINI_API_KEY")
        if not api_key:
            raise ValueError("GEMINI_API_KEY not set in .env file")
        
        self.client = genai.Client(api_key=api_key)
        self.model_name = model_name
        self._cache: Dict[str, GoogleSearchResult] = {}
    
    def search_supplier(self, raw: Dict[str, Any]) -> GoogleSearchResult:
        """
        Search for supplier information using Google/Gemini web search.
        
        Args:
            raw: Supplier row dictionary with keys like Nom, Ville, Postal, Pays
            
        Returns:
            GoogleSearchResult with found information
        """
        # Create cache key
        cache_key = (
            str(raw.get("Nom", "")) + "|" +
            str(raw.get("Ville", "")) + "|" +
            str(raw.get("Postal", "")) + "|" +
            str(raw.get("Pays", ""))
        )
        
        if cache_key in self._cache:
            return self._cache[cache_key]
        
        input_id = str(raw.get("Auxiliaire") or raw.get("input_id") or raw.get("index", ""))
        company_name = str(raw.get("Nom", "") or raw.get("Name", "")).strip()
        country = str(raw.get("Pays", "") or raw.get("Country", "")).strip()
        city = str(raw.get("Ville", "") or raw.get("City", "")).strip() or None
        postal_code = str(raw.get("Postal", "") or raw.get("Postal Code", "")).strip() or None
        
        if not company_name:
            result = GoogleSearchResult(
                input_id=input_id,
                company_name="",
                country=country or "UNKNOWN",
                city=city,
                postal_code=postal_code,
                found_website=None,
                found_address=None,
                found_phone=None,
                found_email=None,
                confidence_score=0.0,
                search_method="NO_NAME",
                raw_data={},
            )
            self._cache[cache_key] = result
            return result
        
        # Build search query
        search_query = company_name
        if city:
            search_query += f" {city}"
        if country and country != "UNKNOWN":
            search_query += f" {country}"
        
        # Use Gemini to search and extract information
        prompt = f"""You are a business information researcher. Search for information about this company and return structured data.

Company: {company_name}
Location: {city or 'Unknown'}, {country or 'Unknown'}
Postal Code: {postal_code or 'Unknown'}

Task: Find the official website, address, phone number, and email for this company.

Return JSON with these keys:
- website: Official company website URL (or null)
- address: Full business address (or null)
- phone: Phone number (or null)
- email: Contact email (or null)
- confidence: Float 0.0-1.0 indicating how confident you are this is the correct company

Search query: "{search_query}"

Return ONLY the JSON object (no markdown, no explanation)."""

        try:
            response = self.client.models.generate_content(
                model=self.model_name,
                contents=prompt
            )
            
            # Extract JSON from response
            text = response.text.strip()
            if "```json" in text:
                text = text.split("```json")[1].split("```")[0]
            elif "```" in text:
                text = text.split("```")[1].split("```")[0]
            
            data = json.loads(text.strip())
            
            result = GoogleSearchResult(
                input_id=input_id,
                company_name=company_name,
                country=country or "UNKNOWN",
                city=city,
                postal_code=postal_code,
                found_website=data.get("website"),
                found_address=data.get("address"),
                found_phone=data.get("phone"),
                found_email=data.get("email"),
                confidence_score=float(data.get("confidence", 0.0)),
                search_method="GEMINI_WEB_SEARCH",
                raw_data=data,
            )
            
            self._cache[cache_key] = result
            return result
            
        except Exception as e:
            # Fallback: return minimal result
            print(f"[GoogleSearch] Error searching for {company_name}: {e}")
            result = GoogleSearchResult(
                input_id=input_id,
                company_name=company_name,
                country=country or "UNKNOWN",
                city=city,
                postal_code=postal_code,
                found_website=None,
                found_address=None,
                found_phone=None,
                found_email=None,
                confidence_score=0.0,
                search_method="ERROR",
                raw_data={"error": str(e)},
            )
            self._cache[cache_key] = result
            return result
    
    def search_batch(self, suppliers: list[Dict[str, Any]]) -> list[GoogleSearchResult]:
        """Search multiple suppliers (can be optimized with batch API calls)."""
        return [self.search_supplier(supplier) for supplier in suppliers]
    
    def result_to_row(self, result: GoogleSearchResult) -> Dict[str, Any]:
        """
        Convert search result to CSV row format.
        Uses unified schema aligned with SIRENE pipeline output.
        """
        return {
            # Common fields
            "input_id": result.input_id,
            "confidence_score": result.confidence_score,
            # SIRENE fields (empty for Google results)
            "resolved_siret": "",  # No SIRET for non-French suppliers
            "official_name": result.company_name,  # Use company_name as official_name
            "match_method": result.search_method,  # Use search_method as match_method
            "alternatives": "",  # No alternatives for Google search
            # Google-specific fields
            "found_website": result.found_website or "",
            "found_address": result.found_address or "",
            "found_phone": result.found_phone or "",
            "found_email": result.found_email or "",
            "country": result.country,
            "city": result.city or "",
            "postal_code": result.postal_code or "",
            "search_method": result.search_method,  # Keep for reference
            # Error field (empty if successful)
            "error": "",
        }
