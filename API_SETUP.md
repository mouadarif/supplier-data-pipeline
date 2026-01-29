# Gemini API Setup & Configuration

## Quick Start

### 1. Create `.env` File in Project Root
Create a file named `.env` in the same directory as `llm_providers.py`:

```env
# API Keys for LLM Integration
GEMINI_API_KEY=your_actual_gemini_api_key_here
```

### 2. Get Your Gemini API Key
1. Go to [Google AI Studio](https://makersuite.google.com/app/apikey)
2. Click "Create API Key"
3. Copy your API key
4. Paste it into the `.env` file

### 3. Install Dependencies
```powershell
cd "C:\Users\mouaad.ibnelaryf\OneDrive - Westfalia Fruit\DATA FOURNISSEURS"
python -m pip install python-dotenv google-genai
```

### 4. Run Pipeline
```powershell
python run_pipeline.py run
```

You should see:
```
[pipeline] GEMINI_API_KEY found, using GeminiLLM
[pipeline] processed=100/2440 (4%) | rate=0.15 rows/sec | ETA=260.0 mins
...
```

## How It Works

### Automatic LLM Selection
The pipeline automatically detects if `GEMINI_API_KEY` is set:
- **With API key**: Uses `GeminiLLM` for intelligent cleaning and arbitration
- **Without API key**: Uses `OfflineHeuristicLLM` (faster but less accurate)

### LLM Caching
The system caches LLM responses to avoid redundant API calls:
- Cache key: combination of (Name, Address, Postal, City)
- Automatically reuses results for duplicate suppliers
- **Saves**: 30-50% API calls if you have duplicate entries

### Error Handling
If Gemini API fails (rate limit, network error, parse error):
- Automatically falls back to offline heuristic
- Logs warning message
- Continues processing (no pipeline crash)

## Verification

### Check if .env is Loaded
```powershell
python -c "import os; from dotenv import load_dotenv; load_dotenv(); print('API Key:', 'SET' if os.getenv('GEMINI_API_KEY') else 'NOT SET')"
```

### Test Gemini Connection
```powershell
python -c "from llm_providers import GeminiLLM; llm = GeminiLLM(); print('Gemini initialized successfully')"
```

If you see errors, check:
1. `.env` file exists in project root
2. `GEMINI_API_KEY` is spelled correctly
3. API key is valid (not expired)
4. python-dotenv is installed

## Performance with Gemini API

### Expected Processing Times
- **Per row**: 3-10 seconds (includes API latency)
- **2440 suppliers**: 2-7 hours (best case) to 1-2 days (with rate limits)

### Rate Limits
- **Free tier**: ~15 requests/minute
- **Paid tier**: Higher limits, faster processing

### Optimization Tips
1. **Run overnight**: Let it complete unattended
2. **Use checkpointing**: Can pause/resume anytime (Ctrl+C to stop)
3. **Monitor cache hits**: Check console for "[GeminiLLM]" messages
4. **Upgrade to paid tier**: Removes rate limits

## Troubleshooting

### "GEMINI_API_KEY is not set"
- Check `.env` file exists in project root
- Verify file is named exactly `.env` (not `.env.txt`)
- Check no extra spaces around `=` sign

### "Module 'dotenv' not found"
```powershell
python -m pip install python-dotenv
```

### ~~"google.generativeai deprecation warning"~~ (FIXED)
- ✅ Migrated to `google.genai` package
- No more deprecation warnings
- See `GEMINI_MIGRATION.md` for details

### Slow Processing
- See `PERFORMANCE.md` for detailed analysis
- Consider using offline mode for testing (remove API key)
- Use `--limit-rows 100` for quick tests

## Offline Mode (No API Key)

For faster testing without API costs:

1. Remove or comment out `GEMINI_API_KEY` from `.env`:
   ```env
   # GEMINI_API_KEY=your_key_here
   ```

2. Run pipeline:
   ```powershell
   python run_pipeline.py run --limit-rows 100
   ```

3. Expected output:
   ```
   [pipeline] No API key found, using OfflineHeuristicLLM
   ```

**Speedup**: 10-20x faster, but less accurate matching.
