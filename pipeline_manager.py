from __future__ import annotations

import csv
import json
import os
import sqlite3
import tempfile
import time
from dataclasses import dataclass, replace
from typing import Any, Dict, Iterable, List, Optional, Set

import duckdb
import pandas as pd

from llm_providers import LLMClient, OfflineHeuristicLLM, GeminiLLM
from matcher_logic import MatchResult, match_supplier_row


@dataclass(frozen=True)
class PipelineConfig:
    supplier_xlsx: str = "Frs.xlsx"
    duckdb_path: str = "sirene.duckdb"
    checkpoint_sqlite: str = "state.sqlite"
    output_csv: str = "results_enriched.csv"
    batch_size: int = 100
    limit_rows: Optional[int] = None
    # New: Allow forcing re-processing of errors
    retry_errors: bool = False


class StateStore:
    def __init__(self, path: str) -> None:
        self.path = path
        # Allow time for busy locks (e.g., antivirus/backup, previous session).
        self.con = sqlite3.connect(path, timeout=30)
        self.con.execute("PRAGMA busy_timeout=5000;")
        try:
            self.con.execute("PRAGMA journal_mode=WAL;")
        except sqlite3.OperationalError as e:
            if "locked" not in str(e).lower():
                raise
        try:
            self.con.execute("PRAGMA synchronous=NORMAL;")
        except sqlite3.OperationalError as e:
            if "locked" not in str(e).lower():
                raise
        self._execute(
            """
            CREATE TABLE IF NOT EXISTS results (
              input_id TEXT PRIMARY KEY,
              resolved_siret TEXT,
              official_name TEXT,
              confidence_score REAL,
              match_method TEXT,
              alternatives_json TEXT,
              error TEXT,
              updated_at_epoch INTEGER
            )
            """
        )
        # Add index on error to quickly find failures
        self._execute("CREATE INDEX IF NOT EXISTS idx_error ON results(error);")
        self.con.commit()

    def _execute(self, sql: str, params: tuple[Any, ...] = ()) -> sqlite3.Cursor:
        for attempt in range(6):
            try:
                if params:
                    return self.con.execute(sql, params)
                return self.con.execute(sql)
            except sqlite3.OperationalError as e:
                if "locked" not in str(e).lower() or attempt == 5:
                    raise
                time.sleep(0.5 * (attempt + 1))
        raise sqlite3.OperationalError("database is locked")

    def get_processed_ids(self, include_errors: bool = False) -> Set[str]:
        """Returns IDs that have been processed."""
        if include_errors:
            query = "SELECT input_id FROM results"
        else:
            query = "SELECT input_id FROM results WHERE error IS NULL"
        rows = self._execute(query).fetchall()
        return {r[0] for r in rows}
    
    def already_done(self) -> set[str]:
        """Legacy method for backward compatibility."""
        return self.get_processed_ids(include_errors=False)

    def upsert_result(self, r: MatchResult) -> None:
        row = r.to_row()
        self._execute(
            """
            INSERT INTO results(input_id, resolved_siret, official_name, confidence_score, match_method, alternatives_json, error, updated_at_epoch)
            VALUES(?,?,?,?,?,?,NULL,?)
            ON CONFLICT(input_id) DO UPDATE SET
              resolved_siret=excluded.resolved_siret,
              official_name=excluded.official_name,
              confidence_score=excluded.confidence_score,
              match_method=excluded.match_method,
              alternatives_json=excluded.alternatives_json,
              error=NULL,
              updated_at_epoch=excluded.updated_at_epoch
            """,
            (
                row["input_id"],
                row["resolved_siret"],
                row["official_name"],
                float(row["confidence_score"]),
                row["match_method"],
                row["alternatives"],
                int(time.time()),
            ),
        )

    def upsert_error(self, input_id: str, err: str) -> None:
        self._execute(
            """
            INSERT INTO results(input_id, error, updated_at_epoch)
            VALUES(?,?,?)
            ON CONFLICT(input_id) DO UPDATE SET
              error=excluded.error,
              updated_at_epoch=excluded.updated_at_epoch
            """,
            (input_id, err, int(time.time())),
        )

    def commit(self) -> None:
        for attempt in range(6):
            try:
                self.con.commit()
                return
            except sqlite3.OperationalError as e:
                if "locked" not in str(e).lower() or attempt == 5:
                    raise
                time.sleep(0.5 * (attempt + 1))

    def export_csv(self, output_csv: str) -> None:
        """
        Export results to CSV with unified schema.
        Includes all columns for compatibility with Google search results.
        """
        rows = self._execute(
            """
            SELECT input_id, resolved_siret, official_name, confidence_score, match_method, alternatives_json, error
            FROM results
            ORDER BY input_id
            """
        ).fetchall()
        
        # Unified schema matching Google search output
        fieldnames = [
            "input_id",
            "resolved_siret",
            "official_name",
            "confidence_score",
            "match_method",
            "alternatives",
            "found_website",  # Empty for SIRENE results
            "found_address",  # Empty for SIRENE results
            "found_phone",    # Empty for SIRENE results
            "found_email",   # Empty for SIRENE results
            "country",       # Empty for SIRENE results
            "city",          # Empty for SIRENE results
            "postal_code",   # Empty for SIRENE results
            "search_method", # Empty for SIRENE results
            "error",
        ]
        
        with open(output_csv, "w", newline="", encoding="utf-8") as f:
            w = csv.writer(f)
            w.writerow(fieldnames)
            # Add empty columns for Google-specific fields
            for row in rows:
                w.writerow([
                    row[0],  # input_id
                    row[1],  # resolved_siret
                    row[2],  # official_name
                    row[3],  # confidence_score
                    row[4],  # match_method
                    row[5],  # alternatives_json
                    "",      # found_website
                    "",      # found_address
                    "",      # found_phone
                    "",      # found_email
                    "",      # country
                    "",      # city
                    "",      # postal_code
                    "",      # search_method
                    row[6] if len(row) > 6 else "",  # error
                ])

    def close(self) -> None:
        self.con.close()


def _make_json_serializable(obj):
    """
    Convert pandas Timestamp and other non-JSON-serializable objects to strings.
    Recursively handles dicts and lists.
    """
    import pandas as pd
    import math
    from datetime import datetime, date
    
    # Check for None/NA first (before type checks)
    if obj is None:
        return None
    
    # Check for pandas NA (only on scalar values, not collections)
    if not isinstance(obj, (dict, list, tuple)) and pd.isna(obj):
        return None
    
    # Handle collections first (before scalar checks)
    if isinstance(obj, dict):
        return {k: _make_json_serializable(v) for k, v in obj.items()}
    elif isinstance(obj, (list, tuple)):
        return [_make_json_serializable(item) for item in obj]
    
    # Handle scalar types
    if isinstance(obj, (pd.Timestamp, datetime, date)):
        return obj.isoformat() if hasattr(obj, 'isoformat') else str(obj)
    elif isinstance(obj, (int, float)) and math.isinf(obj):
        return None
    
    return obj


def _iter_supplier_rows(df: pd.DataFrame) -> Iterable[Dict[str, Any]]:
    """
    Iterate over DataFrame rows efficiently.
    Converts rows to JSON-serializable dictionaries (handles Timestamp objects).
    """
    for i, (_, row) in enumerate(df.iterrows()):
        # Convert row to dict and make JSON-serializable
        d = row.to_dict()
        d = {k: _make_json_serializable(v) for k, v in d.items()}
        # Ensure we have an index if not present
        if "index" not in d:
            d["index"] = str(i)
        yield d


def get_input_id(row: Dict[str, Any]) -> str:
    """Centralize ID extraction logic to ensure consistency."""
    return str(row.get("Auxiliaire") or row.get("Code tiers") or row.get("index", ""))


def run_pipeline(cfg: PipelineConfig, *, llm: Optional[LLMClient] = None) -> None:
    pipeline_start = time.time()
    
    if llm is None:
        if os.getenv("GEMINI_API_KEY"):
            print("[pipeline] GEMINI_API_KEY found, using GeminiLLM")
            llm = GeminiLLM()
        else:
            print("[pipeline] No API key found, using OfflineHeuristicLLM")
            llm = OfflineHeuristicLLM()

    print(f"[pipeline] Loading {cfg.supplier_xlsx}...")
    
    # Preserve IDs/CP as strings to avoid dropping leading zeros (critical for SIRET/CP).
    df = pd.read_excel(
        cfg.supplier_xlsx,
        dtype={
            "Auxiliaire": "string",
            "Postal": "string",
            "Code SIRET": "string",
            "Code NIF": "string",
            "Code NAF": "string",
            "Code tiers": "string",
        },
    )

    # Initialize state store
    try:
        state = StateStore(cfg.checkpoint_sqlite)
    except sqlite3.OperationalError as e:
        if "locked" not in str(e).lower():
            raise
        fallback = os.path.join(tempfile.gettempdir(), f"state_{int(time.time())}.sqlite")
        print(f"[pipeline] checkpoint locked, using temp db: {fallback}")
        cfg = replace(cfg, checkpoint_sqlite=fallback)
        state = StateStore(cfg.checkpoint_sqlite)

    # Determine what to skip
    # If retry_errors is False, we skip anything that exists in DB (success or error)
    # If retry_errors is True, we only skip successes (where error is NULL)
    skip_ids = state.get_processed_ids(include_errors=not cfg.retry_errors)
    print(f"[pipeline] Found {len(skip_ids)} already processed items.")

    # CRITICAL FIX: Filter DataFrame BEFORE applying limit_rows
    # This ensures limit_rows applies to NEW work, not already-done work
    df['_temp_id'] = df.apply(
        lambda x: get_input_id({
            "Auxiliaire": x.get("Auxiliaire"),
            "Code tiers": x.get("Code tiers"),
            "index": str(x.name)
        }),
        axis=1
    )
    
    # Filter out already processed rows
    df_to_process = df[~df['_temp_id'].isin(skip_ids)].copy()
    
    # Apply limit_rows AFTER filtering (so it limits NEW work)
    if cfg.limit_rows is not None:
        print(f"[pipeline] Limiting to {cfg.limit_rows} new rows.")
        df_to_process = df_to_process.head(cfg.limit_rows)
    
    # Remove temporary column
    df_to_process = df_to_process.drop(columns=['_temp_id'], errors='ignore')

    total_to_process = len(df_to_process)
    print(f"[pipeline] Rows to process: {total_to_process}")

    if total_to_process == 0:
        print("[pipeline] Nothing to process.")
        state.export_csv(cfg.output_csv)
        state.close()
        return

    # DuckDB Setup
    con = duckdb.connect(cfg.duckdb_path, read_only=True)
    try:
        try:
            con.execute("LOAD fts;")
        except Exception:
            pass

        # Processing Loop
        batch: List[Dict[str, Any]] = []
        processed_count = 0
        batch_start = time.time()

        for raw in _iter_supplier_rows(df_to_process):
            batch.append(raw)
            
            # Process batch when it reaches batch_size
            if len(batch) >= cfg.batch_size:
                _process_batch(con, batch, state, llm)
                state.commit()
                
                processed_count += len(batch)
                
                # Calculate timing metrics
                elapsed = time.time() - batch_start
                rate = processed_count / elapsed if elapsed > 0 else 0
                remaining = total_to_process - processed_count
                eta_mins = (remaining / rate) / 60 if rate > 0 else 0
                
                print(f"[pipeline] {processed_count}/{total_to_process} "
                      f"({processed_count*100//total_to_process if total_to_process > 0 else 0}%) | "
                      f"rate={rate:.1f}/s | ETA={eta_mins:.1f}m")
                
                batch = []  # Clear batch

        # Process remaining batch
        if batch:
            _process_batch(con, batch, state, llm)
            state.commit()
            processed_count += len(batch)
            print(f"[pipeline] processed={processed_count} (final batch) | total time={(time.time() - pipeline_start)/60:.1f} mins")

    finally:
        con.close()
        state.export_csv(cfg.output_csv)
        state.close()
        
        total_elapsed = time.time() - pipeline_start
        print(f"[pipeline] exported {cfg.output_csv} + checkpoint={cfg.checkpoint_sqlite}")
        print(f"[pipeline] TOTAL TIME: {total_elapsed/60:.1f} minutes ({total_elapsed/3600:.2f} hours)")
        if processed_count > 0:
            print(f"[pipeline] Average: {total_elapsed/processed_count:.2f} seconds per row")


def _process_batch(
    con: duckdb.DuckDBPyConnection,
    batch: List[Dict[str, Any]],
    state: StateStore,
    llm: LLMClient,
) -> None:
    """Process a batch of supplier rows."""
    for raw in batch:
        input_id = get_input_id(raw)
        try:
            # FIX: Ensure raw dict is fully cleaned (defensive check)
            # _iter_supplier_rows should already do this, but this adds extra safety
            raw = {k: _make_json_serializable(v) for k, v in raw.items()}
            
            r = match_supplier_row(con, raw, llm=llm)
            state.upsert_result(r)
        except Exception as e:
            # Log error to console for visibility
            print(f"[ERROR] Processing {input_id}: {type(e).__name__}: {e}")
            state.upsert_error(input_id, f"{type(e).__name__}: {e}")

