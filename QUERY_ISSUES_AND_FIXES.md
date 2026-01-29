# Query Issues and Required Fixes

## 🚨 Critical Issues Found

### Issue 1: Missing Active Establishment Check

**Location:** `matcher_logic.py` - `_strict_local_lookup()` (line 142-156)

**Current Code:**
```sql
SELECT
  e.siret,
  u.denominationUniteLegale AS official_name,
  e.libelleCommuneEtablissement AS city,
  e.address AS address,
  e.is_siege AS is_siege
FROM read_parquet(?) e
JOIN unite_legale_active u USING (siren)
WHERE e.codePostalEtablissement = ?
  AND levenshtein(u.denominationUniteLegale, ?) <= 3
```

**Problem:** Missing `e.etatAdministratifEtablissement = 'A'` check!

**Fixed Code:**
```sql
SELECT
  e.siret,
  u.denominationUniteLegale AS official_name,
  e.libelleCommuneEtablissement AS city,
  e.address AS address,
  e.is_siege AS is_siege
FROM read_parquet(?) e
JOIN unite_legale_active u USING (siren)
WHERE e.etatAdministratifEtablissement = 'A'  -- ADD THIS LINE
  AND e.codePostalEtablissement = ?
  AND levenshtein(u.denominationUniteLegale, ?) <= 3
```

---

### Issue 2: Missing Active Establishment Check in FTS

**Location:** `matcher_logic.py` - `_fetch_establishments_for_sirens()` (line 195-207)

**Current Code:**
```sql
SELECT
  e.siret,
  e.siren,
  u.denominationUniteLegale AS official_name,
  e.libelleCommuneEtablissement AS city,
  e.address AS address,
  e.is_siege AS is_siege
FROM read_parquet(?) e
JOIN unite_legale_active u USING (siren)
WHERE e.siren IN (...)
```

**Problem:** Missing `e.etatAdministratifEtablissement = 'A'` check!

**Fixed Code:**
```sql
SELECT
  e.siret,
  e.siren,
  u.denominationUniteLegale AS official_name,
  e.libelleCommuneEtablissement AS city,
  e.address AS address,
  e.is_siege AS is_siege
FROM read_parquet(?) e
JOIN unite_legale_active u USING (siren)
WHERE e.etatAdministratifEtablissement = 'A'  -- ADD THIS LINE
  AND e.siren IN (...)
```

---

### Issue 3: No City-Only Fallback

**Location:** `matcher_logic.py` - `match_supplier_row()` (line 314-323)

**Current Code:**
```python
if not cleaned.clean_cp:
    return MatchResult(
        input_id=input_id,
        resolved_siret=None,
        official_name=None,
        confidence_score=0.0,
        match_method="NOT_FOUND",
        alternatives=[],
        debug={"step": "NO_CP", **debug},
    )
```

**Problem:** If no postal code, immediately returns NOT_FOUND!

**Required Behavior:**
1. If postal code exists → search by postal code + name
2. If NO postal code BUT city exists → search by city + name
3. If neither → search by name only (nationwide, return ALL matches)

**Proposed Fix:**

```python
# STEP 3-B: FTS broad search
if not cleaned.clean_cp and not cleaned.clean_city:
    # No location data at all
    return MatchResult(
        input_id=input_id,
        resolved_siret=None,
        official_name=None,
        confidence_score=0.0,
        match_method="NOT_FOUND",
        alternatives=[],
        debug={"step": "NO_LOCATION", **debug},
    )

# Use department if postal code exists, otherwise search nationwide
if cleaned.clean_cp:
    dept = cleaned.clean_cp[:2]
    dept_filter = True
else:
    dept = None
    dept_filter = False

# FTS search for company name
fts = _fts_candidates(con, search_token=cleaned.search_token, limit=20)
debug["fts_n"] = len(fts)
sirens = [s for (s, _name, _score) in fts]

# Fetch establishments (filtered by dept if available)
if dept_filter:
    estabs = _fetch_establishments_for_sirens(con, partitions_root=partitions_root, dept=dept, sirens=sirens)
else:
    # Search nationwide (all departments)
    estabs = _fetch_establishments_for_sirens_nationwide(con, partitions_root=partitions_root, sirens=sirens)

# Then filter by city if available
if cleaned.clean_city:
    filtered = []
    for c in estabs:
        c_city = _normalize_city(c.get("city"))
        if Levenshtein.distance(c_city, cleaned.clean_city) <= 3:
            filtered.append(c)
    estabs = filtered
```

---

## 📋 Summary of Required Changes

### 1. Add Active Check to Strict Local Search

**File:** `matcher_logic.py` line 152  
**Add:** `AND e.etatAdministratifEtablissement = 'A'`

### 2. Add Active Check to FTS Establishment Fetch

**File:** `matcher_logic.py` line 205  
**Add:** `WHERE e.etatAdministratifEtablissement = 'A' AND e.siren IN (...)`

### 3. Implement City-Only Fallback

**File:** `matcher_logic.py` line 314-323  
**Change:** Remove immediate NOT_FOUND, implement city-based search

### 4. Add Nationwide Search Function (Optional)

**New function:** `_fetch_establishments_for_sirens_nationwide()`  
**Purpose:** Search all departments when no postal code available

---

## 🧪 Test Cases

### Test 1: Active Company with Postal Code
- **Input:** Name="CARREFOUR", Postal="69001"
- **Expected:** Returns active establishments in 69001

### Test 2: Inactive Establishment
- **Input:** SIRET of closed establishment
- **Expected:** NOT_FOUND (should not return closed establishments)

### Test 3: No Postal Code, Has City
- **Input:** Name="CARREFOUR", City="LYON", Postal=""
- **Expected:** Returns all active CARREFOUR in Lyon area
- **Current:** NOT_FOUND ❌

### Test 4: Multiple Records Same Postal Code
- **Input:** Name="CARREFOUR", Postal="75001"
- **Expected:** Returns ALL active CARREFOUR in 75001
- **Current:** ✅ Works (returns all, then scores them)

---

## 🔍 Search Type Clarification

### Current Search Types:

1. **Exact SIRET Match** (Direct ID)
   - Type: Exact match
   - Filter: `e.siret = ?`

2. **Fuzzy Name Match** (Strict Local)
   - Type: Fuzzy (Levenshtein distance ≤ 3)
   - Example: "CARREFOUR" matches "CARREFOUR", "CAREFOUR" (1 char diff)
   - Filter: `levenshtein(u.denominationUniteLegale, ?) <= 3`

3. **Full-Text Search** (FTS Broad)
   - Type: Partial/fuzzy match using BM25 algorithm
   - Example: "CARREFOUR" matches "CARREFOUR MARKET", "CARREFOUR CITY", etc.
   - Filter: `match_bm25(unite_legale_active, search_token)`

---

## 💡 Recommendations

### Priority 1 (Critical): Add Active Checks
- **Impact:** Prevents returning closed establishments
- **Effort:** Low (2 lines of SQL)
- **Risk:** Low

### Priority 2 (Important): City Fallback
- **Impact:** Handles suppliers without postal codes
- **Effort:** Medium (requires new function + logic)
- **Risk:** Medium (nationwide search could be slow)

### Priority 3 (Enhancement): Return ALL Matches
- **Current:** Already works! Returns all candidates, then scores them
- **No change needed**

---

## 🚀 Next Steps

Would you like me to:
1. ✅ Apply the fixes for active establishment checks?
2. ✅ Implement city-only fallback search?
3. ✅ Add tests to verify the fixes work correctly?
4. ✅ Show you statistics on how many suppliers have no postal code?

Let me know which fixes you want applied!
