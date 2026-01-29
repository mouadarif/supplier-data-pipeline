"""
Unified pipeline runner that:
1. Preprocesses suppliers (country inference, filtering)
2. Processes French suppliers with SIRENE matching
3. Processes non-French suppliers with Google search
4. Combines results
"""
import argparse
import csv
import multiprocessing as mp
import os
import sys
import tempfile
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Optional

from google_search_provider import GoogleSearchProvider
from pipeline_parallel import run_pipeline_parallel, PipelineConfig
from preprocess_suppliers import preprocess_suppliers


def process_non_french_suppliers(
    non_french_xlsx: str,
    output_csv: str,
    *,
    limit_rows: Optional[int] = None,
    max_workers: int = 10,  # Standard for I/O bound tasks
) -> None:
    """
    Process non-French suppliers using Google search with parallel threading.
    
    Uses ThreadPoolExecutor for I/O-bound API calls (much faster than sequential).
    """
    print()
    print("=" * 80)
    print("PROCESSING NON-FRENCH SUPPLIERS (Google Search)")
    print("=" * 80)
    print()
    
    try:
        provider = GoogleSearchProvider()
    except Exception as e:
        print(f"[ERROR] Failed to initialize Google search provider: {e}")
        print("[INFO] Make sure GEMINI_API_KEY is set in .env file")
        return
    
    import pandas as pd
    df = pd.read_excel(non_french_xlsx)
    
    if limit_rows is not None:
        df = df.head(limit_rows)
    
    total_items = len(df)
    print(f"[Google] Processing {total_items} non-French suppliers...")
    
    # Convert to list of dicts for threading
    work_items = df.to_dict('records')
    
    # Wrapper function for thread pool
    def _search_wrapper(row_data: dict) -> Optional[dict]:
        """Wrapper to handle errors in thread pool."""
        try:
            result = provider.search_supplier(row_data)
            return provider.result_to_row(result)
        except Exception as e:
            print(f"[Google] Error processing {row_data.get('Nom', 'unknown')}: {e}")
            # Return error row
            return {
                "input_id": str(row_data.get("Auxiliaire") or row_data.get("Code tiers") or ""),
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
    
    print(f"[Google] Using {max_workers} threads for parallel processing...")
    
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        # Submit all tasks
        future_to_row = {executor.submit(_search_wrapper, row): row for row in work_items}
        
        # Process results as they complete
        for i, future in enumerate(as_completed(future_to_row), 1):
            res = future.result()
            if res:
                results.append(res)
            
            # Progress reporting every 10 items or at milestones
            if i % 10 == 0 or i == total_items:
                elapsed = time.time() - start_time
                rate = i / elapsed if elapsed > 0 else 0
                remaining = total_items - i
                eta_mins = (remaining / rate) / 60 if rate > 0 else 0
                print(f"[Google] Progress: {i}/{total_items} | rate={rate:.1f}/s | ETA={eta_mins:.1f}m")
    
    # Save results
    if results:
        # Ensure consistent field order (unified schema)
        fieldnames = [
            "input_id",
            "resolved_siret",
            "official_name",
            "confidence_score",
            "match_method",
            "alternatives",
            "found_website",
            "found_address",
            "found_phone",
            "found_email",
            "country",
            "city",
            "postal_code",
            "search_method",
            "error",
        ]
        
        with open(output_csv, 'w', encoding='utf-8', newline='') as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            writer.writeheader()
            writer.writerows(results)
        
        elapsed_total = time.time() - start_time
        print(f"[Google] Saved {len(results)} results to {output_csv}")
        print(f"[Google] Total time: {elapsed_total/60:.1f} min ({elapsed_total:.1f} sec)")
        if len(results) > 0:
            print(f"[Google] Average: {elapsed_total/len(results):.2f} sec per supplier")
    else:
        print("[Google] No results to save")
    
    print()
    print("=" * 80)
    print("NON-FRENCH SUPPLIERS PROCESSING COMPLETE")
    print("=" * 80)
    print()


def main():
    parser = argparse.ArgumentParser(
        description="Unified pipeline: Preprocess -> SIRENE (French) + Google (Non-French)"
    )
    parser.add_argument(
        "--input-xlsx",
        default="Frs.xlsx",
        help="Input supplier Excel file (default: Frs.xlsx)"
    )
    parser.add_argument(
        "--duckdb-path",
        default="sirene.duckdb",
        help="Path to DuckDB database (default: sirene.duckdb)"
    )
    parser.add_argument(
        "--output-dir",
        default="results",
        help="Output directory for all results (default: results)"
    )
    parser.add_argument(
        "--workers",
        type=int,
        default=None,
        help=f"Number of parallel workers for SIRENE matching (default: {mp.cpu_count()})"
    )
    parser.add_argument(
        "--google-workers",
        type=int,
        default=10,
        help="Number of threads for Google search (default: 10, I/O bound)"
    )
    parser.add_argument(
        "--limit-rows",
        type=int,
        default=None,
        help="Limit processing to first N rows (default: all rows)"
    )
    parser.add_argument(
        "--skip-preprocess",
        action="store_true",
        help="Skip preprocessing step (use existing preprocessed files)"
    )
    parser.add_argument(
        "--skip-google",
        action="store_true",
        help="Skip Google search for non-French suppliers"
    )
    parser.add_argument(
        "--skip-sirene",
        action="store_true",
        help="Skip SIRENE matching for French suppliers"
    )
    parser.add_argument(
        "--no-filter-inactive",
        action="store_true",
        help="Don't filter suppliers with Date dern. Mouvt = null"
    )
    
    args = parser.parse_args()
    
    # Create output directory
    output_path = Path(args.output_dir)
    output_path.mkdir(exist_ok=True)
    
    print()
    print("=" * 80)
    print("UNIFIED SUPPLIER ENRICHMENT PIPELINE")
    print("=" * 80)
    print()
    
    # Step 1: Preprocessing
    if not args.skip_preprocess:
        print("[STEP 1] Preprocessing suppliers...")
        print("-" * 80)
        try:
            french_xlsx, non_french_xlsx, stats = preprocess_suppliers(
                args.input_xlsx,
                output_dir="preprocessed",
                filter_inactive=not args.no_filter_inactive,
                limit_rows=args.limit_rows,
            )
            print()
            print(f"[STEP 1] [OK] Preprocessing complete!")
            print(f"  French suppliers: {stats['french_suppliers']}")
            print(f"  Non-French suppliers: {stats['non_french_suppliers']}")
            print()
        except Exception as e:
            print(f"[ERROR] Preprocessing failed: {e}")
            import traceback
            traceback.print_exc()
            sys.exit(1)
    else:
        print("[STEP 1] [SKIP] Skipping preprocessing (using existing files)")
        french_xlsx = "preprocessed/suppliers_french.xlsx"
        non_french_xlsx = "preprocessed/suppliers_non_french.xlsx"
        if not Path(french_xlsx).exists() or not Path(non_french_xlsx).exists():
            print(f"[ERROR] Preprocessed files not found: {french_xlsx}, {non_french_xlsx}")
            print("[INFO] Run without --skip-preprocess first")
            sys.exit(1)
        print()
    
    # Step 2: Process French suppliers (SIRENE)
    french_output_csv = str(output_path / "results_french_sirene.csv")
    if not args.skip_sirene:
        print("[STEP 2] Processing French suppliers with SIRENE matching...")
        print("-" * 80)
        try:
            cfg = PipelineConfig(
                supplier_xlsx=french_xlsx,
                duckdb_path=args.duckdb_path,
                checkpoint_sqlite=str(output_path / "checkpoint_french.sqlite"),
                output_csv=french_output_csv,
                batch_size=100,
                limit_rows=None,  # Already limited in preprocessing
            )
            run_pipeline_parallel(
                cfg,
                num_workers=args.workers,
            )
            print()
            print(f"[STEP 2] [OK] SIRENE matching complete!")
            print(f"  Results saved to: {french_output_csv}")
            print()
        except Exception as e:
            print(f"[ERROR] SIRENE matching failed: {e}")
            import traceback
            traceback.print_exc()
    else:
        print("[STEP 2] [SKIP] Skipping SIRENE matching")
        print()
    
    # Step 3: Process non-French suppliers (Google)
    non_french_output_csv = str(output_path / "results_non_french_google.csv")
    if not args.skip_google:
        print("[STEP 3] Processing non-French suppliers with Google search...")
        print("-" * 80)
        try:
            process_non_french_suppliers(
                non_french_xlsx,
                non_french_output_csv,
                limit_rows=None,  # Already limited in preprocessing
                max_workers=args.google_workers,
            )
        except Exception as e:
            print(f"[ERROR] Google search failed: {e}")
            import traceback
            traceback.print_exc()
    else:
        print("[STEP 3] [SKIP] Skipping Google search")
        print()
    
    # Step 4: Combine results (optional)
    print("[STEP 4] Combining results...")
    print("-" * 80)
    combined_output_csv = str(output_path / "results_combined.csv")
    
    try:
        import pandas as pd
        
        results = []
        
        # Load French results
        if Path(french_output_csv).exists():
            df_french = pd.read_csv(french_output_csv)
            print(f"[Combine] Loaded {len(df_french)} French results")
            results.append(df_french)
        
        # Load non-French results
        if Path(non_french_output_csv).exists():
            df_non_french = pd.read_csv(non_french_output_csv)
            print(f"[Combine] Loaded {len(df_non_french)} non-French results")
            results.append(df_non_french)
        
        if results:
            df_combined = pd.concat(results, ignore_index=True)
            df_combined.to_csv(combined_output_csv, index=False)
            print(f"[Combine] [OK] Combined {len(df_combined)} results")
            print(f"  Saved to: {combined_output_csv}")
        else:
            print("[Combine] [WARNING] No results to combine")
        
    except Exception as e:
        print(f"[ERROR] Combining results failed: {e}")
        import traceback
        traceback.print_exc()
    
    print()
    print("=" * 80)
    print("PIPELINE COMPLETE!")
    print("=" * 80)
    print()
    print("Output files:")
    if Path(french_output_csv).exists():
        print(f"  French (SIRENE):     {french_output_csv}")
    if Path(non_french_output_csv).exists():
        print(f"  Non-French (Google): {non_french_output_csv}")
    if Path(combined_output_csv).exists():
        print(f"  Combined:            {combined_output_csv}")
    print()
    print("=" * 80)


if __name__ == "__main__":
    main()
