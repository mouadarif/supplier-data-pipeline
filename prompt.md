ROLE: Senior Data Engineer & Software Architect OBJECTIVE: Build a fault-tolerant, high-performance local data enrichment pipeline to map supplier data (Frs.xlsx) to the official French SIRENE database.

1. DATA & ARCHITECTURE
Input: Frs.xlsx - CONVERT.csv (Dirty data).

Source of Truth: Local SIRENE Parquet files (StockEtablissement & StockUniteLegale).

Engine: Python 3.10+ with DuckDB.

LLM: Gemini 1.5 Flash (JSON Mode) for Cleaning & Tie-Breaking.

Orchestration: Must include Checkpointing (State DB) to allow pausing/resuming.

2. PRE-PROCESSING & OPTIMIZATION (CRITICAL)
Step 0: The "Index-First" Strategy Before processing any rows, the agent must run an initialization script (init_db.py) that:

Partitions StockEtablissement by Department (dept = first 2 digits of zip).

Creates a Full Text Search (FTS) Index on denominationUniteLegale.

Why? To avoid slow LIKE '%token%' scans.

DuckDB Syntax: PRAGMA create_fts_index('etablissements', 'denominationUniteLegale', 'stemmer=french');

Pre-computes Weights: Create a is_siege (Head Office) boolean column to help with tie-breaking.

3. PIPELINE EXECUTION LOGIC (ROW-BY-ROW)
Batch Strategy: Process in batches of 100 rows. Commit results to SQLite checkpoint after each batch.

STEP 1: Strict ID Verification
Trigger: Input has Code SIRET (14 chars) or Code NIF (starts with 'FR').

Query: SELECT * FROM parquet WHERE siret = ? AND etatAdministratifEtablissement = 'A'

Logic:

Matches? -> CONFIDENCE: 100%. Method: DIRECT_ID. STOP.

No Match? -> Nullify the ID and treat as "Unknown". PROCEED.

STEP 2: AI Tokenization & Cleaning (Gemini)
Trigger: Step 1 failed.

Prompt:

"Clean this supplier.

Clean Name: Remove 'SAS', 'SARL'. Remove location (e.g. 'L'OREAL PARIS' -> 'L OREAL').

Search Token: Extract the specific brand name for indexing (e.g., 'BATIMENT' from 'SOC GEN BATIMENT').

Geo: Extract 5-digit CP and City (COG). If CP is invalid, set clean_cp = null. Input: 'CARREFOUR MKT, 69003'"

Output: {"clean_name": "CARREFOUR MARKET", "search_token": "CARREFOUR", "clean_cp": "69003", "clean_city": "LYON"}

STEP 3-A: High-Precision Local Search
Scope: Partition (dept from clean_cp).

Query:

codePostalEtablissement = clean_cp

AND levenshtein(official_name, clean_name) <= 3 (Allow minor typos).

Outcome:

1 Match -> CONFIDENCE: 95%. Method: STRICT_LOCAL. STOP.

0 or >1 Matches -> PROCEED.

STEP 3-B: Broad FTS Search (Performance Optimized)
Scope: Entire Department (dept).

Query: Use DuckDB FTS match_bm25 on search_token.

SELECT score, * FROM etablissements WHERE fts_main_etablissements.match_bm25(denominationUniteLegale, search_token) IS NOT NULL AND dept = ?

Filter: Retain top 20 results. Apply secondary filtering in Python:

Keep if levenshtein(city, input_city) < 3.

Keep if levenshtein(address, input_address) < 10 (loose fuzzy).

STEP 4: Disambiguation & The "Carrefour Problem"
Scenario: Multiple active candidates remain (e.g., 5 branches of the same chain in the same city).

Scoring Algorithm (0-100):

Start at 0.

+40 if Name Similarity > 0.9.

+30 if City matches exactly.

+20 if Address Fuzzy Score > 0.8.

+10 if is_siege (Head Office) is True (Tie-breaker).

Decision:

Top Score > 80? -> CONFIDENCE: <Score>. Method: CALCULATED. STOP.

Top Score < 50? -> Mark NOT_FOUND.

Scores are close (e.g., 80 vs 78)? -> Send to Gemini Arbiter.

Prompt: "Which of these 2 addresses best matches 'Rue des Lilas'?"

4. DATA MAPPING & OUTPUT SCHEMA
Target Parquet Schema Mapping:

Nom -> denominationUniteLegale

Postal -> codePostalEtablissement (Partition Key)

Code SIRET -> siret

Final Output CSV (results_enriched.csv):

input_id: Reference to source row.

resolved_siret: 14 digits.

official_name: From SIRENE.

confidence_score: 0.0 - 1.0.

match_method: DIRECT_ID, STRICT_LOCAL, FTS_BROAD, GEMINI_ARBITER.

alternatives: JSON list of other SIRETs considered (for audit).

5. DELIVERABLES
db_setup.py: Handles Parquet download, Partitioning, and FTS Index Creation.

pipeline_manager.py: Handles Batching (100 rows), Checkpointing (SQLite), and Error Recovery (Try/Except blocks).

matcher_logic.py: Contains the DuckDB queries and Levenshtein logic.

prompts.py: Gemini instructions.