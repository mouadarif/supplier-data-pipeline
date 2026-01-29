from __future__ import annotations

import argparse

from db_setup import Paths, init_duckdb
from pipeline_manager import PipelineConfig, run_pipeline


def main() -> None:
    p = argparse.ArgumentParser(description="Supplier → SIRENE enrichment (local DuckDB + checkpointing)")
    sub = p.add_subparsers(dest="cmd", required=True)

    p_init = sub.add_parser("init-db", help="Build DuckDB + indexes and department partitions")
    p_init.add_argument("--duckdb-path", default=Paths.duckdb_path)
    p_init.add_argument("--ul-parquet", default=Paths.ul_parquet)
    p_init.add_argument("--etab-parquet", default=Paths.etab_parquet)
    p_init.add_argument("--partitions-dir", default=Paths.partitions_dir)
    p_init.add_argument("--sample-row-groups", type=int, default=None, help="Fast dev/test mode (uses first N row groups)")
    p_init.add_argument("--force", action="store_true", help="Force rebuild (overwrite sample + partitions)")

    p_run = sub.add_parser("run", help="Run the row-by-row pipeline with checkpointing")
    p_run.add_argument("--supplier-xlsx", default=Paths.supplier_xlsx)
    p_run.add_argument("--duckdb-path", default=Paths.duckdb_path)
    p_run.add_argument("--checkpoint-sqlite", default="state.sqlite")
    p_run.add_argument("--output-csv", default="results_enriched.csv")
    p_run.add_argument("--batch-size", type=int, default=100)
    p_run.add_argument("--limit-rows", type=int, default=None)

    args = p.parse_args()

    if args.cmd == "init-db":
        init_duckdb(
            duckdb_path=args.duckdb_path,
            ul_parquet=args.ul_parquet,
            etab_parquet=args.etab_parquet,
            partitions_dir=args.partitions_dir,
            sample_row_groups=args.sample_row_groups,
            force_rebuild=args.force,
        )
        return

    if args.cmd == "run":
        cfg = PipelineConfig(
            supplier_xlsx=args.supplier_xlsx,
            duckdb_path=args.duckdb_path,
            checkpoint_sqlite=args.checkpoint_sqlite,
            output_csv=args.output_csv,
            batch_size=args.batch_size,
            limit_rows=args.limit_rows,
        )
        run_pipeline(cfg)
        return

    raise SystemExit(f"Unknown command: {args.cmd}")


if __name__ == "__main__":
    main()

