"""
Batch-enabled LLM provider for parallel processing.
Groups multiple cleaning requests into single API calls for 5-10x speedup.
"""
from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass
from typing import Any, Dict, List, Optional

from google import genai
from dotenv import load_dotenv

from llm_providers import CleanedSupplier, LLMClient

load_dotenv()


def _json_from_text(text: str) -> Dict[str, Any]:
    """Extract first JSON object from model output."""
    m = re.search(r"\{.*\}", text, flags=re.DOTALL)
    if not m:
        raise ValueError("No JSON object found in LLM response")
    return json.loads(m.group(0))


class BatchGeminiLLM(LLMClient):
    """
    Batch-enabled Gemini LLM provider.
    Groups multiple cleaning requests into single API calls for 5-10x speedup.
    
    Usage:
        llm = BatchGeminiLLM()
        results = llm.clean_suppliers_batch([raw1, raw2, ..., raw10])
    """

    def __init__(self, *, model: str = "models/gemini-2.5-flash", batch_size: int = 10) -> None:
        api_key = os.getenv("GEMINI_API_KEY")
        if not api_key:
            raise RuntimeError("GEMINI_API_KEY is not set in environment or .env file")
        self.client = genai.Client(api_key=api_key)
        self.model_name = model
        self.batch_size = batch_size
        self._clean_cache: Dict[str, CleanedSupplier] = {}
        self._arbiter_cache: Dict[str, str] = {}

    def clean_supplier(self, raw: Dict[str, Any]) -> CleanedSupplier:
        """
        Single supplier cleaning (for backward compatibility).
        For better performance, use clean_suppliers_batch() instead.
        """
        results = self.clean_suppliers_batch([raw])
        return results[0]

    def clean_suppliers_batch(self, raw_list: List[Dict[str, Any]]) -> List[CleanedSupplier]:
        """
        Clean multiple suppliers in a single API call.
        
        Args:
            raw_list: List of raw supplier dictionaries
            
        Returns:
            List of CleanedSupplier objects in same order as input
        """
        if not raw_list:
            return []
        
        # Check cache first
        results: List[Optional[CleanedSupplier]] = [None] * len(raw_list)
        uncached_indices: List[int] = []
        uncached_raws: List[Dict[str, Any]] = []
        
        for i, raw in enumerate(raw_list):
            cache_key = (
                str(raw.get("Nom", "")) + "|" +
                str(raw.get("Adresse 1", "")) + "|" +
                str(raw.get("Postal", "")) + "|" +
                str(raw.get("Ville", ""))
            )
            
            if cache_key in self._clean_cache:
                results[i] = self._clean_cache[cache_key]
            else:
                uncached_indices.append(i)
                uncached_raws.append(raw)
        
        # Process uncached items in batches
        if uncached_raws:
            batch_prompt = self._build_batch_prompt(uncached_raws)
            
            try:
                response = self.client.models.generate_content(
                    model=self.model_name,
                    contents=batch_prompt
                )
                
                # Parse batch response
                batch_results = self._parse_batch_response(response.text, len(uncached_raws))
                
                # Update results and cache
                for idx, raw, result in zip(uncached_indices, uncached_raws, batch_results):
                    cache_key = (
                        str(raw.get("Nom", "")) + "|" +
                        str(raw.get("Adresse 1", "")) + "|" +
                        str(raw.get("Postal", "")) + "|" +
                        str(raw.get("Ville", ""))
                    )
                    self._clean_cache[cache_key] = result
                    results[idx] = result
                    
            except Exception as e:
                # Fallback to individual processing if batch fails
                print(f"[BatchGeminiLLM] Batch processing failed, falling back to individual: {e}")
                from llm_providers import OfflineHeuristicLLM
                fallback_llm = OfflineHeuristicLLM()
                for idx, raw in zip(uncached_indices, uncached_raws):
                    result = fallback_llm.clean_supplier(raw)
                    cache_key = (
                        str(raw.get("Nom", "")) + "|" +
                        str(raw.get("Adresse 1", "")) + "|" +
                        str(raw.get("Postal", "")) + "|" +
                        str(raw.get("Ville", ""))
                    )
                    self._clean_cache[cache_key] = result
                    results[idx] = result
        
        return [r for r in results if r is not None]

    def _build_batch_prompt(self, raw_list: List[Dict[str, Any]]) -> str:
        """Build a batch prompt for multiple suppliers."""
        prompt = (
            "You are a French business data cleaning expert.\n"
            "Task: Clean and correct ALL supplier records in this list. Fix any spelling errors.\n\n"
            "Return a JSON ARRAY with one object per supplier.\n\n"
            "Each object must have keys: clean_name, search_token, clean_cp, clean_city.\n\n"
            "Instructions:\n"
            "- clean_name: CORRECT spelling errors (e.g., 'Goggle' -> 'GOOGLE', 'Carfour' -> 'CARREFOUR'), "
            "then convert to UPPERCASE and remove legal suffixes (SAS, SARL, EURL, SA, etc.)\n"
            "- search_token: Extract the most distinctive brand/company token from clean_name "
            "(e.g., 'CARREFOUR' from 'CARREFOUR MARKET', 'GOOGLE' from 'GOOGLE FRANCE')\n"
            "- clean_cp: Extract and normalize 5-digit postal code from Postal or address fields. Set to null if invalid/missing.\n"
            "- clean_city: Correct city spelling if needed, convert to UPPERCASE. Set to null if missing.\n\n"
            "INPUT LIST:\n"
        )
        
        for i, raw in enumerate(raw_list, 1):
            prompt += f"{i}. {json.dumps(raw, ensure_ascii=False, default=str)}\n"
        
        prompt += "\nReturn ONLY the JSON array (no markdown, no explanation).\n"
        prompt += "Example format: [{\"clean_name\": \"GOOGLE\", \"search_token\": \"GOOGLE\", \"clean_cp\": \"75001\", \"clean_city\": \"PARIS\"}, ...]"
        
        return prompt

    def _parse_batch_response(self, text: str, expected_count: int) -> List[CleanedSupplier]:
        """Parse batch API response into list of CleanedSupplier objects."""
        # Try to extract JSON array
        text = text.strip()
        
        # Remove markdown code blocks if present
        if "```json" in text:
            text = text.split("```json")[1].split("```")[0]
        elif "```" in text:
            text = text.split("```")[1].split("```")[0]
        
        text = text.strip()
        
        # Handle potential outer object wrapper
        if text.startswith('{'):
            outer = json.loads(text)
            if "results" in outer and isinstance(outer["results"], list):
                data_list = outer["results"]
            elif isinstance(outer, dict):
                # Try to find array in object
                for key, value in outer.items():
                    if isinstance(value, list):
                        data_list = value
                        break
                else:
                    data_list = [outer]  # Single object
            else:
                data_list = [outer]
        else:
            data_list = json.loads(text)
        
        if not isinstance(data_list, list):
            data_list = [data_list]
        
        # Convert to CleanedSupplier objects
        results = []
        for data in data_list:
            if isinstance(data, dict):
                result = CleanedSupplier(
                    clean_name=str(data.get("clean_name") or ""),
                    search_token=str(data.get("search_token") or ""),
                    clean_cp=(str(data.get("clean_cp")) if data.get("clean_cp") else None),
                    clean_city=(str(data.get("clean_city")) if data.get("clean_city") else None),
                )
                results.append(result)
        
        # Pad or truncate to expected count
        if len(results) < expected_count:
            from llm_providers import OfflineHeuristicLLM
            fallback_llm = OfflineHeuristicLLM()
            # Fill missing with fallback (shouldn't happen, but safety)
            while len(results) < expected_count:
                results.append(CleanedSupplier("", "", None, None))
        elif len(results) > expected_count:
            results = results[:expected_count]
        
        return results

    def arbitrate(self, question: str, a: Dict[str, Any], b: Dict[str, Any]) -> str:
        """Arbitration (not batched, used infrequently)."""
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
            choice = str(data.get("choice", "A")).upper()
            return "A" if choice == "A" else "B"
        except Exception as e:
            print(f"[BatchGeminiLLM] Arbitration failed: {e}")
            return "A"  # Default fallback
