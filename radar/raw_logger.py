from __future__ import annotations

import json
from collections.abc import Iterable
from datetime import UTC, datetime
from pathlib import Path

from .models import Article


class RawLogger:
    def __init__(self, raw_dir: Path):
        self.raw_dir = raw_dir

    def log(
        self,
        articles: Iterable[Article],
        *,
        source_name: str,
        run_id: str | None = None,
    ) -> Path:
        now = datetime.now(UTC)
        date_dir = self.raw_dir / now.date().isoformat()
        safe_source_name = source_name.replace("/", "_").replace("\\", "_")
        filename = (
            f"{safe_source_name}_{run_id}.jsonl"
            if run_id is not None
            else f"{safe_source_name}.jsonl"
        )
        output_path = date_dir / filename
        output_path.parent.mkdir(parents=True, exist_ok=True)

        records_by_link: dict[str, dict[str, object]] = {}
        if output_path.exists():
            try:
                for line in output_path.read_text(encoding="utf-8").splitlines():
                    if line.strip():
                        existing_record = json.loads(line)
                        if isinstance(existing_record, dict):
                            link = str(existing_record.get("link", ""))
                            if link:
                                records_by_link[link] = {
                                    str(key): value for key, value in existing_record.items()
                                }
            except (OSError, json.JSONDecodeError):
                records_by_link = {}

        for article in articles:
            record: dict[str, object] = {
                "title": article.title,
                "link": article.link,
                "summary": article.summary,
                "published": article.published.isoformat() if article.published else None,
                "source": article.source,
                "category": article.category,
                "matched_entities": article.matched_entities,
                "logged_at": now.isoformat(),
            }
            if article.ontology:
                record["ontology"] = article.ontology
            records_by_link[article.link] = record

        with output_path.open("w", encoding="utf-8") as handle:
            for record in records_by_link.values():
                handle.write(json.dumps(record, ensure_ascii=False))
                handle.write("\n")
        return output_path
