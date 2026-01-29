"""
Main entry point for the supplier enrichment pipeline.

This script consolidates all pipeline functionality:
- Database initialization
- Sequential SIRENE matching (French suppliers)
- Parallel SIRENE matching (faster)
- Unified pipeline (preprocessing + SIRENE + Google search)
"""
import argparse
import logging
import multiprocessing as mp
import os
import sys
import tempfile
import time
from pathlib import Path

from db_setup import Paths, init_duckdb
from google_search_provider import GoogleSearchProvider
from pipeline_manager import PipelineConfig, run_pipeline
from pipeline_parallel import run_pipeline_parallel
from preprocess_suppliers import preprocess_suppliers

# Try to import optimized version (may not exist yet)
try:
    from pipeline_parallel_optimized import run_pipeline_parallel_optimized
    HAS_OPTIMIZED = True
except ImportError:
    HAS_OPTIMIZED = False

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='[%(asctime)s] [%(levelname)s] %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
)
logger = logging.getLogger(__name__)


def cmd_init_db(args):
    """Initialize DuckDB database with SIRENE data."""
    init_duckdb(
        duckdb_path=args.duckdb_path,
        ul_parquet=args.ul_parquet,
        etab_parquet=args.etab_parquet,
        partitions_dir=args.partitions_dir,
        sample_row_groups=args.sample_row_groups,
        force_rebuild=args.force,
    )


def cmd_run_sequential(args):
    """Run sequential SIRENE matching (slower but simpler)."""
    try:
        cfg = PipelineConfig(
            supplier_xlsx=args.supplier_xlsx,
            duckdb_path=args.duckdb_path,
            checkpoint_sqlite=args.checkpoint_sqlite,
            output_csv=args.output_csv,
            batch_size=args.batch_size,
            limit_rows=args.limit_rows,
            retry_errors=getattr(args, 'retry_errors', False),
        )
        run_pipeline(cfg)
    except KeyboardInterrupt:
        logger.warning("")
        logger.warning("⚠️  Pipeline interrupted by user (Ctrl+C)")
        logger.info(f"Progress saved to checkpoint: {args.checkpoint_sqlite}")
        logger.info("You can resume by running the same command again.")
        raise


def cmd_run_parallel(args):
    """Run parallel SIRENE matching (5-8x faster)."""
    # Auto-detect workers
    num_workers = args.workers
    if num_workers is None:
        num_workers = mp.cpu_count()
        logger.info(f"Auto-detected {num_workers} CPU cores")
    
    # Use temp checkpoint if not specified (avoids OneDrive locks)
    checkpoint_path = args.checkpoint_sqlite
    if checkpoint_path == "state.sqlite" and not args.use_onedrive_checkpoint:
        temp_dir = tempfile.gettempdir()
        checkpoint_path = os.path.join(temp_dir, "sirene_pipeline_state.sqlite")
        logger.info(f"Using temp checkpoint: {checkpoint_path} (avoids OneDrive locks)")
    
    cfg = PipelineConfig(
        supplier_xlsx=args.supplier_xlsx,
        duckdb_path=args.duckdb_path,
        checkpoint_sqlite=checkpoint_path,
        output_csv=args.output_csv,
        batch_size=args.batch_size,
        limit_rows=args.limit_rows,
        retry_errors=getattr(args, 'retry_errors', False),
    )
    
    run_pipeline_parallel(cfg, num_workers=num_workers)


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


def _row_to_dict(row):
    """
    Convert pandas row to JSON-serializable dictionary.
    Handles Timestamp objects and other pandas types.
    """
    import pandas as pd
    
    if isinstance(row, pd.Series):
        d = row.to_dict()
    elif isinstance(row, dict):
        d = row.copy()
    else:
        d = dict(row)
    
    # Convert Timestamps and other non-serializable types
    return {k: _make_json_serializable(v) for k, v in d.items()}


def _load_supplier_file(file_path: str, limit_rows=None):
    """
    Load supplier file with memory-efficient reading.
    Supports Excel, CSV, and Parquet formats.
    """
    import pandas as pd
    from pathlib import Path
    
    path = Path(file_path)
    
    # Determine file type
    if path.suffix.lower() == '.parquet':
        logger.info(f"Loading Parquet file: {file_path}")
        df = pd.read_parquet(file_path)
    elif path.suffix.lower() == '.csv':
        logger.info(f"Loading CSV file: {file_path}")
        # Use chunked reading for very large CSV files
        try:
            # Try reading in chunks if file is large (>100MB)
            file_size = path.stat().st_size
            if file_size > 100 * 1024 * 1024:  # 100MB
                logger.info(f"Large CSV file detected ({file_size / 1024 / 1024:.1f}MB), using chunked reading")
                chunks = []
                total_rows = 0  # FIX: Track rows with integer counter, not DataFrame concat
                
                for chunk in pd.read_csv(file_path, chunksize=10000, dtype={'Postal': str, 'Code SIRET': str}):
                    chunks.append(chunk)
                    total_rows += len(chunk)
                    
                    # FIX: Check limit using counter, not expensive concat operation
                    if limit_rows and total_rows >= limit_rows:
                        logger.info(f"Reached limit of {limit_rows} rows")
                        # Trim last chunk if needed
                        if total_rows > limit_rows:
                            excess = total_rows - limit_rows
                            chunks[-1] = chunks[-1].iloc[:-excess]
                        break
                
                # FIX: Concat only ONCE at the end (not inside loop)
                df = pd.concat(chunks, ignore_index=True)
            else:
                df = pd.read_csv(file_path, dtype={'Postal': str, 'Code SIRET': str})
        except Exception:
            # Fallback to regular reading
            df = pd.read_csv(file_path, dtype={'Postal': str, 'Code SIRET': str})
    else:
        # Excel file
        logger.info(f"Loading Excel file: {file_path}")
        df = pd.read_excel(
            file_path,
            dtype={'Postal': str, 'Code SIRET': str, 'Auxiliaire': str, 'Code tiers': str}
        )
    
    if limit_rows is not None:
        df = df.head(limit_rows)
        logger.info(f"Limited to {limit_rows} rows")
    
    logger.info(f"Loaded {len(df)} rows from {file_path}")
    return df


def process_non_french_suppliers(
    non_french_file: str,
    output_csv: str,
    *,
    limit_rows=None,
    max_workers: int = 10,
    rate_limit_delay: float = 0.0,
) -> None:
    """
    Process non-French suppliers using Google search with threading.
    
    Args:
        non_french_file: Path to Excel/CSV/Parquet file
        output_csv: Output CSV path
        limit_rows: Limit number of rows to process
        max_workers: Number of threads (default: 10)
        rate_limit_delay: Delay between API calls in seconds (default: 0.0)
    """
    from concurrent.futures import ThreadPoolExecutor, as_completed
    import csv
    
    logger.info("=" * 80)
    logger.info("PROCESSING NON-FRENCH SUPPLIERS (Google Search)")
    logger.info("=" * 80)
    
    try:
        provider = GoogleSearchProvider()
    except Exception as e:
        logger.error(f"Failed to initialize Google search provider: {e}")
        return
    
    # Load file with memory-efficient reading
    df = _load_supplier_file(non_french_file, limit_rows=limit_rows)
    
    # Convert to JSON-serializable dicts (handles Timestamp objects)
    work_items = [_row_to_dict(row) for _, row in df.iterrows()]
    total_items = len(work_items)
    logger.info(f"Processing {total_items} suppliers with {max_workers} threads")
    if rate_limit_delay > 0:
        logger.info(f"Rate limiting: {rate_limit_delay}s delay between API calls")
    
    def _search_wrapper(row_data):
        try:
            result = provider.search_supplier(row_data)
            return provider.result_to_row(result)
        except Exception as e:
            logger.warning(f"Error processing {row_data.get('Nom', 'unknown')}: {e}")
            return {
                "input_id": str(row_data.get("Auxiliaire") or ""),
                "confidence_score": 0.0,
                "resolved_siret": "",
                "official_name": str(row_data.get("Nom", "")),
                "match_method": "ERROR",
                "alternatives": "",
                "found_website": "",
                "found_address": "",
                "found_phone": "",
                "found_email": "",
                "country": str(row_data.get("Pays", "")),
                "city": str(row_data.get("Ville", "")),
                "postal_code": str(row_data.get("Postal", "")),
                "search_method": "ERROR",
                "error": f"{type(e).__name__}: {e}",
            }
    
    results = []
    start_time = time.time()
    
    try:
        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            # FIX: Throttle task submission to prevent API bursts
            future_to_row = {}
            for i, row in enumerate(work_items):
                # Throttle submission if rate limit is requested
                # This ensures we don't queue all tasks instantly, preventing bursts
                if rate_limit_delay > 0 and i > 0:
                    # Distribute delay across workers to smooth out submission rate
                    # If we have N workers and want R requests/sec, space submissions by R/N
                    time.sleep(rate_limit_delay / max_workers)
                
                future = executor.submit(_search_wrapper, row)
                future_to_row[future] = row
            
            try:
                for i, future in enumerate(as_completed(future_to_row), 1):
                    res = future.result()
                    if res:
                        results.append(res)
                    if i % 10 == 0 or i == total_items:
                        elapsed = time.time() - start_time
                        rate = i / elapsed if elapsed > 0 else 0
                        remaining = total_items - i
                        eta_mins = (remaining / rate) / 60 if rate > 0 else 0
                        logger.info(f"Progress: {i}/{total_items} | rate={rate:.1f}/s | ETA={eta_mins:.1f}m")
            except KeyboardInterrupt:
                logger.warning("⚠️  Interrupted by user (Ctrl+C)")
                logger.info(f"Saving {len(results)} completed results...")
                # Cancel remaining futures
                for future in future_to_row:
                    future.cancel()
                # Don't wait for executor shutdown - exit immediately
                executor.shutdown(wait=False)
                raise
    except KeyboardInterrupt:
        logger.warning("⚠️  Pipeline interrupted")
        raise
    
    if results:
        fieldnames = [
            "input_id", "resolved_siret", "official_name", "confidence_score",
            "match_method", "alternatives", "found_website", "found_address",
            "found_phone", "found_email", "country", "city", "postal_code",
            "search_method", "error",
        ]
        with open(output_csv, 'w', encoding='utf-8', newline='') as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            writer.writeheader()
            writer.writerows(results)
        logger.info(f"Saved {len(results)} results to {output_csv}")
    else:
        logger.warning("No results to save")


def cmd_run_unified(args):
    """Run unified pipeline: preprocessing + SIRENE (French) + Google (non-French)."""
    # Set logging level
    logging.getLogger().setLevel(getattr(logging, args.log_level))
    
    output_path = Path(args.output_dir)
    output_path.mkdir(exist_ok=True)
    
    logger.info("=" * 80)
    logger.info("UNIFIED SUPPLIER ENRICHMENT PIPELINE")
    logger.info("=" * 80)
    
    # FIX: Clean up old output files to prevent stale data merging
    french_output_csv = str(output_path / "results_french_sirene.csv")
    non_french_output_csv = str(output_path / "results_non_french_google.csv")
    combined_output_csv = str(output_path / "results_combined.csv")
    
    old_files = []
    if Path(french_output_csv).exists():
        old_files.append(french_output_csv)
    if Path(non_french_output_csv).exists():
        old_files.append(non_french_output_csv)
    if Path(combined_output_csv).exists():
        old_files.append(combined_output_csv)
    
    if old_files:
        logger.warning("=" * 80)
        logger.warning("WARNING: Old output files detected from previous run!")
        logger.warning("=" * 80)
        for f in old_files:
            file_path = Path(f)
            mtime = file_path.stat().st_mtime
            from datetime import datetime
            mod_time = datetime.fromtimestamp(mtime).strftime("%Y-%m-%d %H:%M:%S")
            logger.warning(f"  - {f} (last modified: {mod_time})")
        
        if args.clean_output:
            logger.info("Cleaning old output files (--clean-output flag set)...")
            for f in old_files:
                try:
                    Path(f).unlink()
                    logger.info(f"  [OK] Deleted: {f}")
                except Exception as e:
                    logger.warning(f"  [WARN] Could not delete {f}: {e}")
        else:
            logger.warning("These files will be merged with new results, potentially mixing stale and fresh data!")
            logger.warning("Use --clean-output flag to automatically delete old files before running.")
            logger.warning("=" * 80)
    
    # Initialize output paths (reset after cleanup check)
    french_output_csv = str(output_path / "results_french_sirene.csv")
    non_french_output_csv = str(output_path / "results_non_french_google.csv")
    combined_output_csv = str(output_path / "results_combined.csv")
    
    try:
        # Step 1: Preprocessing
        if not args.skip_preprocess:
            logger.info("[STEP 1] Preprocessing suppliers...")
            logger.info("-" * 80)
            try:
                french_xlsx, non_french_xlsx, stats = preprocess_suppliers(
                    args.input_xlsx,
                    output_dir="preprocessed",
                    filter_inactive=not args.no_filter_inactive,
                    limit_rows=args.limit_rows,
                )
                logger.info(f"[STEP 1] [OK] Preprocessing complete!")
                logger.info(f"  French suppliers: {stats['french_suppliers']}")
                logger.info(f"  Non-French suppliers: {stats['non_french_suppliers']}")
            except Exception as e:
                logger.error(f"Preprocessing failed: {e}", exc_info=True)
                sys.exit(1)
        else:
            logger.info("[STEP 1] [SKIP] Skipping preprocessing")
            french_xlsx = "preprocessed/suppliers_french.xlsx"
            non_french_xlsx = "preprocessed/suppliers_non_french.xlsx"
            if not Path(french_xlsx).exists() or not Path(non_french_xlsx).exists():
                logger.error("Preprocessed files not found")
                sys.exit(1)
        
        # Step 2: Process French suppliers (SIRENE)
        french_output_csv = str(output_path / "results_french_sirene.csv")
        if not args.skip_sirene:
            logger.info("[STEP 2] Processing French suppliers with SIRENE matching...")
            logger.info("-" * 80)
            try:
                num_workers = args.workers or mp.cpu_count()
                cfg = PipelineConfig(
                    supplier_xlsx=french_xlsx,
                    duckdb_path=args.duckdb_path,
                    checkpoint_sqlite=str(output_path / "checkpoint_french.sqlite"),
                    output_csv=french_output_csv,
                    batch_size=100,
                    limit_rows=None,
                )
                run_pipeline_parallel(cfg, num_workers=num_workers)
                logger.info(f"[STEP 2] [OK] SIRENE matching complete!")
                logger.info(f"  Results saved to: {french_output_csv}")
            except Exception as e:
                logger.error(f"SIRENE matching failed: {e}", exc_info=True)
        else:
            logger.info("[STEP 2] [SKIP] Skipping SIRENE matching")
        
        # Step 3: Process non-French suppliers (Google)
        non_french_output_csv = str(output_path / "results_non_french_google.csv")
        if not args.skip_google:
            logger.info("[STEP 3] Processing non-French suppliers with Google search...")
            logger.info("-" * 80)
            try:
                process_non_french_suppliers(
                    non_french_xlsx,
                    non_french_output_csv,
                    limit_rows=None,
                    max_workers=args.google_workers,
                    rate_limit_delay=args.google_rate_limit,
                )
            except Exception as e:
                logger.error(f"Google search failed: {e}", exc_info=True)
        else:
            logger.info("[STEP 3] [SKIP] Skipping Google search")
        
        # Step 4: Combine results
        logger.info("[STEP 4] Combining results...")
        logger.info("-" * 80)
        combined_output_csv = str(output_path / "results_combined.csv")
        
        try:
            import pandas as pd
            
            results = []
            unified_cols = [
                "input_id", "resolved_siret", "official_name", "confidence_score",
                "match_method", "alternatives", "found_website", "found_address",
                "found_phone", "found_email", "country", "city", "postal_code",
                "search_method", "error"
            ]
            
            if Path(french_output_csv).exists():
                df_french = pd.read_csv(french_output_csv)
                for col in unified_cols:
                    if col not in df_french.columns:
                        df_french[col] = ""
                df_french = df_french[unified_cols]
                results.append(df_french)
                logger.info(f"[Combine] Loaded {len(df_french)} French results")
            
            if Path(non_french_output_csv).exists():
                df_non_french = pd.read_csv(non_french_output_csv)
                for col in unified_cols:
                    if col not in df_non_french.columns:
                        df_non_french[col] = ""
                df_non_french = df_non_french[unified_cols]
                results.append(df_non_french)
                logger.info(f"[Combine] Loaded {len(df_non_french)} non-French results")
            
            if results:
                df_combined = pd.concat(results, ignore_index=True)
                df_combined.to_csv(combined_output_csv, index=False)
                logger.info(f"[Combine] [OK] Combined {len(df_combined)} results")
                logger.info(f"  Saved to: {combined_output_csv}")
            else:
                logger.warning("[Combine] No results to combine")
            
        except Exception as e:
            logger.error(f"Combining results failed: {e}", exc_info=True)
        
        logger.info("=" * 80)
        logger.info("PIPELINE COMPLETE!")
        logger.info("=" * 80)
        logger.info("Output files:")
        if french_output_csv and Path(french_output_csv).exists():
            logger.info(f"  French (SIRENE):     {french_output_csv}")
        if non_french_output_csv and Path(non_french_output_csv).exists():
            logger.info(f"  Non-French (Google): {non_french_output_csv}")
        if combined_output_csv and Path(combined_output_csv).exists():
            logger.info(f"  Combined:            {combined_output_csv}")
    
    except KeyboardInterrupt:
        logger.warning("")
        logger.warning("=" * 80)
        logger.warning("⚠️  PIPELINE INTERRUPTED BY USER (Ctrl+C)")
        logger.warning("=" * 80)
        logger.info("Partial results may have been saved:")
        if Path(french_output_csv).exists():
            try:
                import pandas as pd
                df = pd.read_csv(french_output_csv)
                logger.info(f"  French (SIRENE):     {french_output_csv} ({len(df)} rows)")
            except:
                logger.info(f"  French (SIRENE):     {french_output_csv}")
        if Path(non_french_output_csv).exists():
            try:
                import pandas as pd
                df = pd.read_csv(non_french_output_csv)
                logger.info(f"  Non-French (Google): {non_french_output_csv} ({len(df)} rows)")
            except:
                logger.info(f"  Non-French (Google): {non_french_output_csv}")
        logger.info("")
        logger.info("You can resume by running the same command again.")
        logger.info("Already processed rows will be skipped automatically.")
        raise


def main():
    parser = argparse.ArgumentParser(
        description="Supplier enrichment pipeline - Main entry point",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Initialize database
  python run.py init-db

  # Run sequential pipeline (simple, slower)
  python run.py sequential --supplier-xlsx Frs.xlsx

  # Run parallel pipeline (fast, recommended)
  python run.py parallel --supplier-xlsx Frs.xlsx --workers 8

  # Run optimized parallel pipeline (fastest, with batch API calls)
  python run.py parallel-optimized --supplier-xlsx Frs.xlsx --workers 8 --api-batch-size 10

  # Run unified pipeline (preprocessing + SIRENE + Google)
  python run.py unified --input-xlsx Frs.xlsx
        """
    )
    
    subparsers = parser.add_subparsers(dest="command", required=True, help="Command to run")
    
    # init-db command
    p_init = subparsers.add_parser("init-db", help="Initialize DuckDB database with SIRENE data")
    p_init.add_argument("--duckdb-path", default=Paths.duckdb_path)
    p_init.add_argument("--ul-parquet", default=Paths.ul_parquet)
    p_init.add_argument("--etab-parquet", default=Paths.etab_parquet)
    p_init.add_argument("--partitions-dir", default=Paths.partitions_dir)
    p_init.add_argument("--sample-row-groups", type=int, default=None)
    p_init.add_argument("--force", action="store_true")
    
    # sequential command
    p_seq = subparsers.add_parser("sequential", help="Run sequential SIRENE matching (slower but simpler)")
    p_seq.add_argument("--supplier-xlsx", default="Frs.xlsx")
    p_seq.add_argument("--duckdb-path", default="sirene.duckdb")
    p_seq.add_argument("--checkpoint-sqlite", default="state.sqlite")
    p_seq.add_argument("--output-csv", default="results_enriched.csv")
    p_seq.add_argument("--batch-size", type=int, default=100)
    p_seq.add_argument("--limit-rows", type=int, default=None)
    p_seq.add_argument("--retry-errors", action="store_true")
    
    # parallel command
    p_par = subparsers.add_parser("parallel", help="Run parallel SIRENE matching (5-8x faster, recommended)")
    p_par.add_argument("--supplier-xlsx", default="Frs.xlsx")
    p_par.add_argument("--duckdb-path", default="sirene.duckdb")
    p_par.add_argument("--checkpoint-sqlite", default="state.sqlite")
    p_par.add_argument("--output-csv", default="results_enriched.csv")
    p_par.add_argument("--batch-size", type=int, default=100)
    p_par.add_argument("--limit-rows", type=int, default=None)
    p_par.add_argument("--workers", type=int, default=None, help=f"Number of workers (default: {mp.cpu_count()})")
    p_par.add_argument("--use-onedrive-checkpoint", action="store_true", help="Use OneDrive checkpoint (slower)")
    p_par.add_argument("--retry-errors", action="store_true")
    
    # parallel-optimized command
    p_opt = subparsers.add_parser("parallel-optimized", help="Run optimized parallel with batch API calls (10-20x faster)")
    p_opt.add_argument("--supplier-xlsx", default="Frs.xlsx")
    p_opt.add_argument("--duckdb-path", default="sirene.duckdb")
    p_opt.add_argument("--checkpoint-sqlite", default="state.sqlite")
    p_opt.add_argument("--output-csv", default="results_enriched.csv")
    p_opt.add_argument("--batch-size", type=int, default=100, help="SQLite commit batch size")
    p_opt.add_argument("--api-batch-size", type=int, default=10, help="API call batch size (rows per API call)")
    p_opt.add_argument("--limit-rows", type=int, default=None)
    p_opt.add_argument("--workers", type=int, default=None, help=f"Number of workers (default: {mp.cpu_count()})")
    p_opt.add_argument("--use-onedrive-checkpoint", action="store_true", help="Use OneDrive checkpoint (slower)")
    p_opt.add_argument("--retry-errors", action="store_true")
    
    # unified command
    p_uni = subparsers.add_parser("unified", help="Run unified pipeline: preprocessing + SIRENE + Google")
    p_uni.add_argument("--input-xlsx", default="Frs.xlsx", help="Input file (Excel, CSV, or Parquet)")
    p_uni.add_argument("--duckdb-path", default="sirene.duckdb")
    p_uni.add_argument("--output-dir", default="results")
    p_uni.add_argument("--workers", type=int, default=None, help=f"SIRENE workers (default: {mp.cpu_count()})")
    p_uni.add_argument("--google-workers", type=int, default=10, help="Google search threads (default: 10)")
    p_uni.add_argument("--google-rate-limit", type=float, default=0.0, help="Delay between Google API calls in seconds (default: 0.0)")
    p_uni.add_argument("--limit-rows", type=int, default=None)
    p_uni.add_argument("--skip-preprocess", action="store_true")
    p_uni.add_argument("--skip-google", action="store_true")
    p_uni.add_argument("--skip-sirene", action="store_true")
    p_uni.add_argument("--no-filter-inactive", action="store_true")
    p_uni.add_argument("--clean-output", action="store_true", help="Automatically delete old output files before running (prevents stale data merging)")
    p_uni.add_argument("--log-level", default="INFO", choices=["DEBUG", "INFO", "WARNING", "ERROR"], help="Logging level (default: INFO)")
    
    args = parser.parse_args()
    
    # Route to appropriate command handler
    if args.command == "init-db":
        cmd_init_db(args)
    elif args.command == "sequential":
        cmd_run_sequential(args)
    elif args.command == "parallel":
        cmd_run_parallel(args)
    elif args.command == "parallel-optimized":
        cmd_run_parallel_optimized(args)
    elif args.command == "unified":
        cmd_run_unified(args)
    else:
        parser.print_help()
        sys.exit(1)


if __name__ == "__main__":
    main()
