# Supplier Enrichment Logic - Detailed Diagram

## Complete Data Flow with Columns & Decisions

```mermaid
flowchart TD
    Start([Start: Load Frs.xlsx]) --> LoadCols[INPUT COLUMNS:<br/>- Auxiliaire input_id<br/>- Nom company name<br/>- Code SIRET 14 digits<br/>- Code NIF FR VAT number<br/>- Code NAF activity code<br/>- Adresse 1,2,3<br/>- Postal 5-digit code<br/>- Ville city name]
    
    LoadCols --> CheckDone{Already in<br/>state.sqlite?}
    CheckDone -- Yes --> Skip[SKIP: Use cached result]
    CheckDone -- No --> Step1
    
    Skip --> End
    
    Step1[STEP 1: Direct ID Lookup]
    Step1 --> HasSIRET{Has Code SIRET<br/>14 digits?}
    
    HasSIRET -- Yes --> QuerySIRET[Query DuckDB:<br/>SELECT * FROM StockEtablissement<br/>WHERE siret = ? AND<br/>etatAdministratifEtablissement = 'A']
    
    QuerySIRET --> FoundSIRET{Found active<br/>establishment?}
    
    FoundSIRET -- Yes --> Result1[OUTPUT:<br/>- resolved_siret = siret<br/>- official_name = denominationUniteLegale<br/>- confidence_score = 1.0<br/>- match_method = DIRECT_ID]
    
    Result1 --> End([Save to state.sqlite<br/>Export to CSV])
    
    FoundSIRET -- No --> Step2
    HasSIRET -- No --> Step2
    
    Step2[STEP 2: LLM Cleaning]
    Step2 --> LLMChoice{API Key set?}
    
    LLMChoice -- Yes --> Gemini[Gemini API Call:<br/>Clean supplier data]
    LLMChoice -- No --> Offline[Offline Heuristic:<br/>Rule-based cleaning]
    
    Gemini --> Cleaned[CLEANED DATA:<br/>- clean_name: uppercase, no suffixes<br/>- search_token: most distinctive word<br/>- clean_cp: 5-digit postal code<br/>- clean_city: normalized city]
    
    Offline --> Cleaned
    
    Cleaned --> HasCP{Has clean_cp<br/>postal code?}
    
    HasCP -- No --> NotFound[OUTPUT:<br/>- resolved_siret = NULL<br/>- confidence_score = 0.0<br/>- match_method = NOT_FOUND]
    
    NotFound --> End
    
    HasCP -- Yes --> Step3A[STEP 3-A: Strict Local Search]
    
    Step3A --> QueryLocal[Query DuckDB:<br/>dept = clean_cp[:2]<br/>SELECT * FROM dept partition<br/>WHERE codePostalEtablissement = clean_cp<br/>AND levenshtein official_name, clean_name ≤ 3]
    
    QueryLocal --> LocalResults{How many<br/>results?}
    
    LocalResults -- Exactly 1 --> Result2[OUTPUT:<br/>- resolved_siret = siret<br/>- official_name = denominationUniteLegale<br/>- confidence_score = 0.95<br/>- match_method = STRICT_LOCAL]
    
    Result2 --> End
    
    LocalResults -- 0 or >1 --> Step3B[STEP 3-B: FTS Broad Search]
    
    Step3B --> FTS[Query DuckDB FTS:<br/>SELECT * FROM unite_legale_active<br/>WHERE fts_main.match_bm25<br/>search_token IS NOT NULL<br/>LIMIT 20]
    
    FTS --> GetSirens[Extract SIRENs from<br/>FTS results]
    
    GetSirens --> FetchEstabs[Fetch Establishments:<br/>dept = clean_cp[:2]<br/>SELECT * FROM dept partition<br/>WHERE siren IN ...sirens...]
    
    FetchEstabs --> Filter[Filter Candidates:<br/>- levenshtein city, input_city < 3<br/>- levenshtein address, input_address < 10]
    
    Filter --> AnyCandidates{Any candidates<br/>remaining?}
    
    AnyCandidates -- No --> NotFound
    
    AnyCandidates -- Yes --> Score[Score Each Candidate 0-100:<br/>+40 if name_similarity > 0.9<br/>+30 if city exact match<br/>+20 if address_similarity > 0.8<br/>+10 if is_siege = TRUE]
    
    Score --> TopScore{Top score?}
    
    TopScore -- > 80 --> Result3[OUTPUT:<br/>- resolved_siret = top.siret<br/>- official_name = top.denominationUniteLegale<br/>- confidence_score = score/100<br/>- match_method = CALCULATED<br/>- alternatives = next 5 SIRETs]
    
    Result3 --> End
    
    TopScore -- < 50 --> NotFound
    
    TopScore -- 50-80 --> Close{Top 2 scores<br/>within 2 points?}
    
    Close -- No --> Result3
    
    Close -- Yes --> Arbiter[Gemini Arbiter:<br/>Which address matches best?<br/>Option A vs Option B]
    
    Arbiter --> Result4[OUTPUT:<br/>- resolved_siret = chosen.siret<br/>- official_name = chosen.denominationUniteLegale<br/>- confidence_score = score/100<br/>- match_method = GEMINI_ARBITER<br/>- alternatives = other candidates]
    
    Result4 --> End
    
    style Start fill:#e1f5e1
    style End fill:#e1f5e1
    style Result1 fill:#c8e6c9
    style Result2 fill:#c8e6c9
    style Result3 fill:#c8e6c9
    style Result4 fill:#c8e6c9
    style NotFound fill:#ffcdd2
    style Gemini fill:#fff9c4
    style Arbiter fill:#fff9c4
    style QuerySIRET fill:#e3f2fd
    style QueryLocal fill:#e3f2fd
    style FTS fill:#e3f2fd
    style FetchEstabs fill:#e3f2fd
```

## Column Mapping Details

### Input Columns (from Frs.xlsx)

| Column | Type | Purpose | Example |
|--------|------|---------|---------|
| `Auxiliaire` | string | Unique supplier ID | "402BSYSTEM00" |
| `Nom` | string | Company name (dirty) | "2B SYSTEM SAS" |
| `Code SIRET` | string | 14-digit establishment ID | "50113813700013" |
| `Code NIF` | string | FR VAT number | "FR67880632237" |
| `Code NAF` | string | Activity code | "6201Z" |
| `Adresse 1` | string | Address line 1 | "38 RUE DU SEMINAIRE" |
| `Adresse 2` | string | Address line 2 | "BAT G5D" |
| `Adresse 3` | string | Address line 3 | "" |
| `Postal` | string | 5-digit postal code | "94626" |
| `Ville` | string | City name | "RUNGIS CEDEX" |

### LLM Cleaned Columns

| Column | Type | Transformation | Example |
|--------|------|---------------|---------|
| `clean_name` | string | Uppercase, remove SAS/SARL/etc | "2B SYSTEM" |
| `search_token` | string | Most distinctive word | "SYSTEM" |
| `clean_cp` | string | Normalized 5-digit code | "94626" |
| `clean_city` | string | Uppercase city | "RUNGIS" |

### Database Columns Used (from SIRENE)

**From StockUniteLegale:**
- `siren` (9 digits) - Company identifier
- `denominationUniteLegale` - Official company name
- `activitePrincipaleUniteLegale` - NAF code
- `etatAdministratifUniteLegale` - 'A' = active, 'F' = closed

**From StockEtablissement:**
- `siret` (14 digits) - Establishment identifier
- `siren` (9 digits) - Company identifier
- `codePostalEtablissement` - Postal code
- `libelleCommuneEtablissement` - City name
- `libelleVoieEtablissement` - Street name
- `numeroVoieEtablissement` - Street number
- `etablissementSiege` - TRUE if head office
- `etatAdministratifEtablissement` - 'A' = active

### Output Columns (results_enriched.csv)

| Column | Type | Description | Example |
|--------|------|-------------|---------|
| `input_id` | string | Original Auxiliaire | "402BSYSTEM00" |
| `resolved_siret` | string | Matched 14-digit SIRET | "50113813700013" |
| `official_name` | string | Official company name from SIRENE | "2B SYSTEM" |
| `confidence_score` | float | 0.0 to 1.0 confidence | 0.95 |
| `match_method` | string | How match was found | "STRICT_LOCAL" |
| `alternatives` | JSON array | Alternative SIRETs (if any) | ["123...", "456..."] |

## Decision Logic Summary

### Confidence Score Mapping

| Score | Match Method | Meaning |
|-------|-------------|---------|
| 1.0 | DIRECT_ID | Exact SIRET match in database |
| 0.95 | STRICT_LOCAL | Single match with same postal code + name ≤3 char difference |
| 0.80-0.99 | CALCULATED | High similarity score (name + city + address) |
| 0.50-0.79 | CALCULATED or GEMINI_ARBITER | Medium score, possibly with LLM arbitration |
| 0.0 | NOT_FOUND | No viable match found |

### Match Method Hierarchy

1. **DIRECT_ID** (fastest, most reliable)
   - Input has valid SIRET
   - Found in active establishments
   - No further processing needed

2. **STRICT_LOCAL** (fast, high precision)
   - Same postal code
   - Very similar name (≤3 characters difference)
   - Exactly 1 match

3. **CALCULATED** (slower, good precision)
   - FTS search for similar names
   - Filter by geography
   - Score based on multiple factors
   - Top score above threshold

4. **GEMINI_ARBITER** (slowest, highest accuracy)
   - Multiple candidates with close scores
   - LLM decides between top 2
   - Used when automated scoring is uncertain

5. **NOT_FOUND** (no match)
   - No postal code available
   - No candidates after filtering
   - All scores below threshold

## Performance Characteristics

| Step | Time per Row | Database Access | API Calls |
|------|-------------|-----------------|-----------|
| Already Done Check | <0.01s | SQLite read | 0 |
| Direct ID Lookup | 0.1s | DuckDB read | 0 |
| LLM Cleaning (Gemini) | 1-3s | None | 1 |
| LLM Cleaning (Offline) | <0.01s | None | 0 |
| Strict Local Search | 0.5-1s | DuckDB read | 0 |
| FTS Broad Search | 1-2s | DuckDB read | 0 |
| Scoring | 0.5-1s | None (in memory) | 0 |
| Gemini Arbiter | 1-3s | None | 1 |

**Total per row**: 3-10 seconds (with Gemini), 1-3 seconds (offline)
