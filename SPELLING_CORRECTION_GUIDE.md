# Company Name Spelling Correction Guide

## Overview

Your pipeline now uses **Gemini AI** to automatically correct misspelled company names, remove legal suffixes, and normalize company data before matching against the SIRENE database.

---

## ✅ What Was Updated

### 1. Enhanced LLM Prompt (`llm_providers.py`)

**Before:**
```python
"- clean_name: uppercase, remove legal suffixes (SAS, SARL, etc.)"
```

**After:**
```python
"- clean_name: CORRECT spelling errors (e.g., 'Goggle' -> 'GOOGLE', 'Carfour' -> 'CARREFOUR'), 
then convert to UPPERCASE and remove legal suffixes (SAS, SARL, EURL, SA, etc.)"
```

**Key Improvements:**
- ✅ Explicitly asks Gemini to **fix spelling errors**
- ✅ Provides clear examples (Goggle → GOOGLE)
- ✅ More detailed instructions for extracting search tokens
- ✅ Better handling of postal codes and cities

---

## 🧪 Test Results

Run `python test_gemini_spelling.py` to verify:

| Original Input          | Corrected Output      | Status |
|-------------------------|-----------------------|--------|
| `Goggle France SAS`     | `GOOGLE FRANCE`       | ✅ PASS |
| `Carfour Market SARL`   | `CARREFOUR MARKET`    | ✅ PASS |
| `Amazone France`        | `AMAZON FRANCE`       | ✅ PASS |
| `Micorsoft France`      | `MICROSOFT FRANCE`    | ✅ PASS |
| `Aple Store`            | `APPLE STORE`         | ✅ PASS |

**Conclusion:** Gemini successfully corrects common misspellings before database search!

---

## 📊 How It Works in the Pipeline

### Step-by-Step Process

```
┌─────────────────────────────────────┐
│ INPUT: Excel Row                    │
│ Nom: "Goggle France SAS"            │
│ Ville: "Paris"                      │
│ Postal: "75001"                     │
└─────────────────────────────────────┘
           ↓
┌─────────────────────────────────────┐
│ STEP 1: Send to Gemini API          │
│ → Fix spelling errors               │
│ → Remove legal suffixes             │
│ → Extract search token              │
│ → Normalize location data           │
└─────────────────────────────────────┘
           ↓
┌─────────────────────────────────────┐
│ OUTPUT: Cleaned Data                │
│ clean_name: "GOOGLE FRANCE"         │
│ search_token: "GOOGLE"              │
│ clean_cp: "75001"                   │
│ clean_city: "PARIS"                 │
└─────────────────────────────────────┘
           ↓
┌─────────────────────────────────────┐
│ STEP 2: Search SIRENE Database      │
│ → Use "GOOGLE" to search            │
│ → Match with postal code            │
│ → Find exact SIRET                  │
└─────────────────────────────────────┘
           ↓
┌─────────────────────────────────────┐
│ RESULT: Enriched Data               │
│ resolved_siret: "00032517500065"    │
│ resolution_method: "fts_broad"      │
└─────────────────────────────────────┘
```

---

## 🔍 The Exact Code

Located in `llm_providers.py`, `clean_supplier()` method:

```python
def clean_supplier(self, raw: Dict[str, Any]) -> CleanedSupplier:
    # Build the prompt
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
        f"Input: {json.dumps(raw, ensure_ascii=False)}\n\n"
        "Return ONLY the JSON object (no markdown, no explanation)."
    )
    
    # Call Gemini API
    response = self.client.models.generate_content(
        model=self.model_name,
        contents=prompt
    )
    
    # Parse response
    data = _json_from_text(response.text)
    
    # Return cleaned data
    return CleanedSupplier(
        clean_name=str(data.get("clean_name") or ""),
        search_token=str(data.get("search_token") or ""),
        clean_cp=(str(data.get("clean_cp")) if data.get("clean_cp") else None),
        clean_city=(str(data.get("clean_city")) if data.get("clean_city") else None),
    )
```

---

## 🚀 Performance Optimization: Batch Processing

### Current Implementation (Per-Row)
- **Speed:** ~2 seconds per company
- **Pros:** Simple, good error handling, easy checkpointing
- **Cons:** Slower for large datasets (1000+ companies)

### Batch Processing (Future Enhancement)
- **Speed:** Process 10-20 companies per API call
- **Expected speedup:** 5-10x faster
- **Demo:** Run `python batch_gemini_example.py`

**Example Output:**
```
Time: 5.68 seconds for 5 companies
Average: 1.14 seconds per company
Sequential: 5 × 2s = 10s
Batch: 5.68s
Speedup: 1.8x faster
```

**To Integrate Batch Processing:**
1. Group companies in batches of 10-20
2. Send all to Gemini in one prompt
3. Parse array response
4. Requires more complex error handling

---

## 💰 Cost Considerations

### Caching Strategy
The pipeline **caches** cleaned results to avoid redundant API calls:

```python
cache_key = f"{Nom}|{Adresse}|{Postal}|{Ville}"
if cache_key in self._clean_cache:
    return self._clean_cache[cache_key]  # No API call!
```

**Benefits:**
- If "CARREFOUR MARKET" appears 50 times → only 1 API call
- Saves money and time
- Works across the entire pipeline run

### API Costs (Gemini 2.5 Flash)
- **Input:** $0.15 per 1M tokens
- **Output:** $0.60 per 1M tokens
- **Typical cost:** ~$0.0005 per company
- **1000 companies:** ~$0.50

**Tip:** Use `--limit-rows 100` for testing to avoid unnecessary costs.

---

## 📋 Quick Commands

```bash
# Test spelling correction (no pipeline run)
python test_gemini_spelling.py

# Demo batch processing
python batch_gemini_example.py

# Run full pipeline with Gemini
python run_fast.py --workers 4

# Test on first 100 rows
python run_fast.py --limit-rows 100
```

---

## 🔧 Troubleshooting

### Problem: Gemini not correcting obvious misspellings

**Solution:** Check your prompt in `llm_providers.py` line 174-183. Make sure it includes:
```python
"CORRECT spelling errors (e.g., 'Goggle' -> 'GOOGLE')"
```

### Problem: Too slow with large datasets

**Solution 1:** Use parallel processing
```bash
python run_fast.py --workers 8
```

**Solution 2:** Implement batch processing (see `batch_gemini_example.py`)

### Problem: API quota exceeded

**Solution:**
1. Check [Google AI Studio](https://aistudio.google.com/apikey) for quota
2. Reduce `--workers` to avoid rate limits
3. Add delays between requests (modify `llm_providers.py`)

---

## ✅ Summary

**Your pipeline now:**
1. ✅ Corrects misspelled company names (Goggle → GOOGLE)
2. ✅ Removes legal suffixes (SAS, SARL, etc.)
3. ✅ Extracts distinctive search tokens
4. ✅ Normalizes postal codes and cities
5. ✅ Caches results to save money
6. ✅ Falls back to heuristics if API fails

**Ready to run:**
```bash
python run_fast.py --workers 4
```

**Expected results:**
- Better matching accuracy (fewer "unmatched" rows)
- Handles data entry errors automatically
- Works with your existing SIRENE database

---

## 📚 Related Documentation

- `API_SETUP.md` - Gemini API setup instructions
- `SPEEDUP_GUIDE.md` - Performance optimization tips
- `ENRICHMENT_LOGIC_DIAGRAM.md` - Full pipeline flow
- `PERFORMANCE.md` - Deep performance analysis

---

**Questions?** Run the test scripts or check the code in `llm_providers.py` line 162-204.
