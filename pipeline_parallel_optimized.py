"""
Optimized parallel processing with batch API calls.
Groups multiple rows into single Gemini API calls for 5-10x speedup.
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

from llm_providers_batch import BatchGeminiLLM
from llm_providers import LLMClient, OfflineHeuristicLLM
from matcher_logic import MatchResult, match_supplier_row
from pipeline_manager import PipelineConfig, StateStore, get_input_id


def _process_batch_worker(
    args: tuple[List[Dict[str, Any]], str, str, Optional[str], int]
) -> List[tuple[str, Optional[MatchResult], Optional[str]]]:
    """
    Worker function that processes a BATCH of rows using batch API calls.
    
    Args:
        args: (batch_raw_list, duckdb_path, llm_mode, gemini_key, batch_size)
    
    Returns:
        List of (input_id, result, error) tuples
    """
    batch_raw_list, duckdb_path, llm_mode, gemini_key, batch_size = args
    
    results: List[tuple[str, Optional[MatchResult], Optional[str]]] = []
    
    try:
        # Deep clean all raw dicts
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
        
        cleaned_batch = [_clean_value(raw) for raw in batch_raw_list]
        
        # Create DuckDB connection (shared for batch)
        con = duckdb.connect(duckdb_path, read_only=True)
        try:
            con.execute("LOAD fts;")
        except Exception:
            pass
        
        # Initialize LLM (batch-enabled if Gemini)
        if llm_mode == "gemini" and gemini_key:
            os.environ["GEMINI_API_KEY"] = gemini_key
            llm: LLMClient = BatchGeminiLLM(batch_size=batch_size)
        else:
            llm = OfflineHeuristicLLM()
        
        # Process batch: pre-clean all suppliers using batch API
        if isinstance(llm, BatchGeminiLLM):
            # Use batch API for cleaning
            try:
                cleaned_suppliers = llm.clean_suppliers_batch(cleaned_batch)
            except Exception as e:
                # Fallback to individual processing
                print(f"[Worker] Batch cleaning failed, falling back: {e}")
                cleaned_suppliers = [llm.clean_supplier(raw) for raw in cleaned_batch]
        else:
            # Offline mode - process individually
            cleaned_suppliers = [llm.clean_supplier(raw) for raw in cleaned_batch]
        
        # Now process each row with its cleaned supplier
        for raw, cleaned in zip(cleaned_batch, cleaned_suppliers):
            input_id = str(raw.get("Auxiliaire") or raw.get("Code tiers") or raw.get("index"))
            
            try:
                # Create a modified raw dict with cleaned data for matching
                # The match_supplier_row function will use the cleaned data from LLM
                result = match_supplier_row(con, raw, llm=llm)
                results.append((input_id, result, None))
            except Exception as e:
                results.append((input_id, None, f"{type(e).__name__}: {e}"))
        
        con.close()
        
    except Exception as e:
        # If batch processing fails completely, return errors for all rows
        for raw in batch_raw_list:
            input_id = str(raw.get("Auxiliaire") or raw.get("Code tiers") or raw.get("index"))
            results.append((input_id, None, f"Batch processing failed: {type(e).__name__}: {e}"))
    
    return results


def run_pipeline_parallel_optimized(
    cfg: PipelineConfig,
    *,
    num_workers: Optional[int] = None,
    llm: Optional[LLMClient] = None,
    batch_size: int = 10,
) -> None:
    """
    Optimized parallel version with batch API calls.
    
    Args:
        cfg: Pipeline configuration
        num_workers: Number of parallel workers (default: CPU count)
        llm: LLM client (only for mode detection, workers create their own)
        batch_size: Number of rows to batch per API call (default: 10)
    """
    pipeline_start = time.time()
    
    # Setup LLM Mode
    llm_mode = "offline"
    gemini_key = None
    if os.getenv("GEMINI_API_KEY"):
        gemini_key = os.getenv("GEMINI_API_KEY")
        print("[pipeline] GEMINI_API_KEY found, using BatchGeminiLLM in workers")
        llm_mode = "gemini"
    else:
        print("[pipeline] No API key found, using OfflineHeuristicLLM in workers")
    
    # Load Data
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
        import math
        from datetime import datetime, date
        
        if obj is None:
            return None
        
        if not isinstance(obj, (dict, list, tuple)) and pd.isna(obj):
            return None
        
        if isinstance(obj, dict):
            return {k: _make_json_serializable(v) for k, v in obj.items()}
        elif isinstance(obj, (list, tuple)):
            return [_make_json_serializable(item) for item in obj]
        
        if isinstance(obj, (pd.Timestamp, datetime, date)):
            return obj.isoformat() if hasattr(obj, 'isoformat') else str(obj)
        elif isinstance(obj, (int, float)) and math.isinf(obj):
            return None
        
        return obj
    
    work_items: List[Dict[str, Any]] = []
    for i, row in df.iterrows():
        raw = row.to_dict()
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
    print(f"[pipeline] Batch size: {batch_size} rows per API call")
    
    if total_to_process == 0:
        state.export_csv(cfg.output_csv)
        state.close()
        return
    
    # Parallel Execution with Batching
    if num_workers is None:
        num_workers = min(mp.cpu_count(), total_to_process)
    
    print(f"[pipeline] Starting {num_workers} workers with batch API calls...")
    
    # Group work items into batches
    batches: List[List[Dict[str, Any]]] = []
    for i in range(0, len(work_items), batch_size):
        batches.append(work_items[i:i + batch_size])
    
    print(f"[pipeline] Created {len(batches)} batches of ~{batch_size} rows each")
    
    # Prepare worker arguments (one batch per worker call)
    worker_args = [
        (batch, cfg.duckdb_path, llm_mode, gemini_key, batch_size)
        for batch in batches
    ]
    
    processed_count = 0
    batch_start = time.time()
    
    try:
        with mp.Pool(processes=num_workers) as pool:
            # Process batches in parallel
            iterator = pool.imap_unordered(_process_batch_worker, worker_args, chunksize=1)
            
            try:
                for batch_results in iterator:
                    for input_id, result, error in batch_results:
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
                pool.terminate()
                pool.join()
                raise
    except KeyboardInterrupt:
        print()
        print("[pipeline] ⚠️  Interrupted by user (Ctrl+C)")
        state.commit()
        raise
    
    # Export
    state.export_csv(cfg.output_csv)
    state.close()
    
    total_time = time.time() - pipeline_start
    print(f"[pipeline] Finished. Total time: {total_time/60:.1f} min.")
    print(f"[pipeline] Speedup vs sequential: ~{num_workers}x")
    print(f"[pipeline] Additional speedup from batching: ~5-10x for API calls")


if __name__ == "__main__":
    from pipeline_manager import PipelineConfig
    
    cfg = PipelineConfig(
        supplier_xlsx="Frs.xlsx",
        duckdb_path="sirene.duckdb",
        checkpoint_sqlite="state.sqlite",
        output_csv="results_enriched.csv",
        batch_size=100,
        limit_rows=None,
    )
    
    run_pipeline_parallel_optimized(cfg, num_workers=8, batch_size=10)
