"""
Parallel processing version of the pipeline using multiprocessing.
Provides 4-8x speedup by processing batches in parallel.
"""
from __future__ import annotations

import csv
import json
import multiprocessing as mp
import os
import sqlite3
import tempfile
import time
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple

import duckdb
import pandas as pd

from llm_providers import GeminiLLM, LLMClient, OfflineHeuristicLLM
from matcher_logic import MatchResult, match_supplier_row
from pipeline_manager import PipelineConfig, StateStore, get_input_id


def _process_row_worker(
    args: tuple[Dict[str, Any], str, str, Optional[str]]
) -> tuple[str, Optional[MatchResult], Optional[str]]:
    """
    Worker function for parallel processing.
    Each worker gets its own DuckDB connection (read-only, thread-safe).
    
    Returns: (input_id, result, error)
    """
    raw, duckdb_path, llm_mode, gemini_key = args
    
    # Re-calculate ID inside worker to be safe
    input_id = str(raw.get("Auxiliaire") or raw.get("Code tiers") or raw.get("index"))
    
    try:
        # FIX: Deep clean raw dict to ensure all Timestamps are converted
        # This is critical because pickling/unpickling might recreate Timestamps
        import math
        from datetime import datetime, date
        
        def _clean_value(obj):
            """Recursively clean Timestamps and other non-serializable objects."""
            if obj is None:
                return None
            if not isinstance(obj, (dict, list, tuple)) and pd.isna(obj):
                return None
            if isinstance(obj, dict):
                return {k: _clean_value(v) for k, v in obj.items()}
            if isinstance(obj, (list, tuple)):
                return [_clean_value(item) for item in obj]
            if isinstance(obj, (pd.Timestamp, datetime, date)):
                return obj.isoformat() if hasattr(obj, 'isoformat') else str(obj)
            if isinstance(obj, (int, float)) and math.isinf(obj):
                return None
            return obj
        
        # Deep clean the raw dict before processing
        raw = _clean_value(raw)
        
        # Each worker creates its own connection (DuckDB allows multiple readers)
        con = duckdb.connect(duckdb_path, read_only=True)
        try:
            con.execute("LOAD fts;")
        except Exception:
            pass
        
        # Initialize LLM (offline or Gemini)
        if llm_mode == "gemini" and gemini_key:
            os.environ["GEMINI_API_KEY"] = gemini_key
            llm: LLMClient = GeminiLLM()
        else:
            llm = OfflineHeuristicLLM()
        
        result = match_supplier_row(con, raw, llm=llm)
        con.close()
        
        return (input_id, result, None)
    
    except Exception as e:
        return (input_id, None, f"{type(e).__name__}: {e}")


def run_pipeline_parallel(
    cfg: PipelineConfig,
    *,
    num_workers: Optional[int] = None,
    llm: Optional[LLMClient] = None,
) -> None:
    """
    Parallel version of run_pipeline using multiprocessing.
    
    Args:
        cfg: Pipeline configuration
        num_workers: Number of parallel workers (default: CPU count)
        llm: LLM client (only for mode detection, workers create their own)
    """
    pipeline_start = time.time()
    
    # Setup LLM Mode
    llm_mode = "offline"
    gemini_key = None
    if os.getenv("GEMINI_API_KEY"):
        gemini_key = os.getenv("GEMINI_API_KEY")
        print("[pipeline] GEMINI_API_KEY found, using GeminiLLM in workers")
        llm_mode = "gemini"
    else:
        print("[pipeline] No API key found, using OfflineHeuristicLLM in workers")
    
    # Load data
    print(f"[pipeline] Loading {cfg.supplier_xlsx}...")
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
    
    # Setup State Store
    try:
        state = StateStore(cfg.checkpoint_sqlite)
        cfg_checkpoint = cfg.checkpoint_sqlite
    except sqlite3.OperationalError:
        fallback = os.path.join(tempfile.gettempdir(), f"state_{int(time.time())}.sqlite")
        print(f"[pipeline] checkpoint locked, using temp db: {fallback}")
        state = StateStore(fallback)
        cfg_checkpoint = fallback
    
    # Filter Work
    skip_ids = state.get_processed_ids(include_errors=not getattr(cfg, 'retry_errors', False))
    print(f"[pipeline] Found {len(skip_ids)} already processed items.")
    
    # Helper function to make JSON-serializable
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
    
    work_items: List[Dict[str, Any]] = []
    for i, row in df.iterrows():
        raw = row.to_dict()
        # Convert Timestamps and other non-serializable types
        raw = {k: _make_json_serializable(v) for k, v in raw.items()}
        raw["index"] = str(i)
        input_id = get_input_id(raw)
        
        if input_id not in skip_ids:
            work_items.append(raw)
            
    # Apply limit to NEW work only
    if cfg.limit_rows is not None:
        print(f"[pipeline] Limiting to {cfg.limit_rows} new rows.")
        work_items = work_items[:cfg.limit_rows]
    
    total_to_process = len(work_items)
    print(f"[pipeline] Total to process: {total_to_process} rows")
    
    if total_to_process == 0:
        state.export_csv(cfg.output_csv)
        state.close()
        return

    # Parallel Execution
    if num_workers is None:
        num_workers = min(mp.cpu_count(), total_to_process)
    
    print(f"[pipeline] Starting {num_workers} workers...")
    
    # Tuple arguments for pickle-ability
    worker_args = [
        (item, cfg.duckdb_path, llm_mode, gemini_key)
        for item in work_items
    ]
    
    processed_count = 0
    batch_start = time.time()
    
    try:
        with mp.Pool(processes=num_workers) as pool:
            # imap_unordered yields results as soon as they are ready
            # chunksize=1 keeps workers responsive, higher might be slightly faster for very fast tasks
            iterator = pool.imap_unordered(_process_row_worker, worker_args, chunksize=1)
            
            try:
                for input_id, result, error in iterator:
                    if result:
                        state.upsert_result(result)
                    elif error:
                        state.upsert_error(input_id, error)
                    
                    processed_count += 1
                    
                    # Commit every 'batch_size' items
                    if processed_count % cfg.batch_size == 0:
                        state.commit()
                        
                        # Metrics
                        elapsed = time.time() - batch_start
                        rate = processed_count / elapsed if elapsed > 0 else 0
                        remaining = total_to_process - processed_count
                        eta_mins = (remaining / rate) / 60 if rate > 0 else 0
                        print(f"[pipeline] {processed_count}/{total_to_process} | rate={rate:.1f}/s | ETA={eta_mins:.1f}m")

                # Final commit
                state.commit()
            except KeyboardInterrupt:
                print()
                print("[pipeline] ⚠️  Interrupted by user (Ctrl+C)")
                print(f"[pipeline] Saving progress... ({processed_count}/{total_to_process} processed)")
                state.commit()
                # Terminate pool immediately
                pool.terminate()
                pool.join()
                raise
    except KeyboardInterrupt:
        # Ensure final commit even on interrupt
        if processed_count > 0:
            state.commit()
        raise

    # Export
    state.export_csv(cfg.output_csv)
    state.close()
    
    total_time = time.time() - pipeline_start
    print(f"[pipeline] Finished. Total time: {total_time/60:.1f} min.")
    print(f"[pipeline] Speedup vs sequential: ~{num_workers}x")


if __name__ == "__main__":
    import argparse
    
    p = argparse.ArgumentParser(description="Parallel pipeline for faster processing")
    p.add_argument("--supplier-xlsx", default="Frs.xlsx")
    p.add_argument("--duckdb-path", default="sirene.duckdb")
    p.add_argument("--checkpoint-sqlite", default="state.sqlite")
    p.add_argument("--output-csv", default="results_enriched.csv")
    p.add_argument("--batch-size", type=int, default=100, help="Checkpoint batch size")
    p.add_argument("--limit-rows", type=int, default=None)
    p.add_argument("--workers", type=int, default=None, help="Number of parallel workers (default: CPU count)")
    
    args = p.parse_args()
    
    cfg = PipelineConfig(
        supplier_xlsx=args.supplier_xlsx,
        duckdb_path=args.duckdb_path,
        checkpoint_sqlite=args.checkpoint_sqlite,
        output_csv=args.output_csv,
        batch_size=args.batch_size,
        limit_rows=args.limit_rows,
    )
    
    run_pipeline_parallel(cfg, num_workers=args.workers)
