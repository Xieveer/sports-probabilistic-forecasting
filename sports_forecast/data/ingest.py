from pathlib import Path

import pandas as pd


def process_tournament(source_dir: Path, raw_root: Path) -> None:
    tournament_name = source_dir.name
    source_json = source_dir / "source.json"
    output_parquet = raw_root / tournament_name / "matches.parquet"

    if not source_json.exists():
        print(f"[ingest] Пропускаю {tournament_name}: нет source.json")
        return

    print(f"[ingest] Турнир {tournament_name}: загружаю {source_json}")
    df = pd.read_json(source_json, lines=False)

    print(f"[ingest] Турнир {tournament_name}: {len(df)} записей")
    output_parquet.parent.mkdir(parents=True, exist_ok=True)
    df.to_parquet(output_parquet, index=False)
    print(f"[ingest] Турнир {tournament_name}: parquet → {output_parquet}")


def run() -> None:
    source_root = Path("data/source")
    raw_root = Path("data/raw")

    if not source_root.exists():
        raise FileNotFoundError(f"Каталог с источниками не найден: {source_root}")

    for tournament_dir in sorted(p for p in source_root.iterdir() if p.is_dir()):
        process_tournament(tournament_dir, raw_root)


if __name__ == "__main__":
    run()
