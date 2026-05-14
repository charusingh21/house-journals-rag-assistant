#!/usr/bin/env python3
"""Create the RAG collection and ingest House Journal PDFs.

This script is intentionally separate from setup.sh. Metadata indexing is fast
and local; full RAG ingestion can take minutes and depends on the NVIDIA RAG
Blueprint services being healthy.
"""

from __future__ import annotations

import argparse
import json
import sqlite3
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any


def request_json(url: str, method: str = "GET", payload: dict[str, Any] | None = None) -> dict[str, Any]:
    body = None if payload is None else json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=body,
        headers={"Content-Type": "application/json"} if body else {},
        method=method,
    )
    with urllib.request.urlopen(req, timeout=60) as response:
        data = response.read().decode("utf-8") or "{}"
    return json.loads(data)


def create_collection(base_url: str, collection: str) -> None:
    try:
        current = request_json(f"{base_url}/collections")
        names = {item.get("collection_name") for item in current.get("collections", [])}
        if collection in names:
            print(f"Collection already exists: {collection}")
            return
    except Exception as exc:
        print(f"Warning: could not list collections before create: {exc}")

    payload = {
        "collection_name": collection,
        "description": "Pennsylvania House Journal PDFs for the legislative research assistant demo",
        "tags": ["house-journals", "legislative-research", "demo"],
        "owner": "demo",
        "created_by": "house-journals-ingest",
        "business_domain": "Legal",
        "status": "Active",
        "metadata_schema": [
            {
                "name": "filename",
                "type": "string",
                "description": "Source PDF filename",
            },
            {
                "name": "document_date",
                "type": "string",
                "description": "Date inferred from filename",
            },
        ],
    }
    result = request_json(f"{base_url}/collection", method="POST", payload=payload)
    print(result.get("message") or f"Created collection: {collection}")


def existing_documents(base_url: str, collection: str) -> set[str]:
    try:
        data = request_json(f"{base_url}/documents?collection_name={collection}")
    except Exception as exc:
        print(f"Warning: could not list existing documents: {exc}")
        return set()
    return {doc.get("document_name") for doc in data.get("documents", [])}


def indexed_rows(db_path: Path, latest: int) -> list[tuple[str, str]]:
    conn = sqlite3.connect(db_path)
    try:
        rows = conn.execute(
            """
            select filename, journal_date
            from documents
            order by journal_date desc, filename desc
            limit ?
            """,
            (latest,),
        ).fetchall()
    finally:
        conn.close()
    return [(str(filename), str(journal_date or "")) for filename, journal_date in rows]


def upload_pdf(base_url: str, collection: str, pdf_path: Path, journal_date: str) -> bool:
    payload = {
        "collection_name": collection,
        "blocking": True,
        "split_options": {"chunk_size": 1024, "chunk_overlap": 150},
        "custom_metadata": [
            {"filename": pdf_path.name, "document_date": journal_date}
        ],
        "generate_summary": False,
    }
    command = [
        "curl",
        "-sS",
        "-X",
        "POST",
        f"{base_url}/documents",
        "-F",
        f"documents=@{pdf_path}",
        "-F",
        "data=" + json.dumps(payload),
    ]
    proc = subprocess.run(command, text=True, capture_output=True, timeout=1800)
    output = (proc.stdout or "") + (proc.stderr or "")
    failed = "failed_documents" in output and '"failed_documents":[]' not in output
    if proc.returncode != 0 or failed:
        print(output[:2000], file=sys.stderr)
        return False
    return True


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--pdf-dir", default="HouseJournalSample")
    parser.add_argument("--db", default="data/house_journals_index.sqlite")
    parser.add_argument("--collection", default="house_journals_full_demo")
    parser.add_argument("--ingestor-url", default="http://127.0.0.1:8082/v1")
    parser.add_argument("--latest", type=int, default=40)
    args = parser.parse_args()

    pdf_dir = Path(args.pdf_dir)
    db_path = Path(args.db)
    if not pdf_dir.exists():
        raise SystemExit(f"PDF folder not found: {pdf_dir}")
    if not db_path.exists():
        raise SystemExit(f"Metadata index not found: {db_path}")

    create_collection(args.ingestor_url, args.collection)
    already = existing_documents(args.ingestor_url, args.collection)
    rows = indexed_rows(db_path, args.latest)
    print(f"Target PDFs: {len(rows)}. Already ingested: {len(already)}.")

    success = 0
    failed = 0
    started = time.time()
    for index, (filename, journal_date) in enumerate(rows, start=1):
        pdf_path = pdf_dir / filename
        if filename in already:
            print(f"{index}/{len(rows)} skip existing {filename}")
            continue
        if not pdf_path.exists():
            print(f"{index}/{len(rows)} missing {pdf_path}", file=sys.stderr)
            failed += 1
            continue
        print(f"{index}/{len(rows)} ingest {filename}")
        if upload_pdf(args.ingestor_url, args.collection, pdf_path, journal_date):
            print(f"{index}/{len(rows)} done {filename}")
            success += 1
        else:
            print(f"{index}/{len(rows)} failed {filename}", file=sys.stderr)
            failed += 1

    final_docs = existing_documents(args.ingestor_url, args.collection)
    elapsed = time.time() - started
    print(
        f"Finished in {elapsed:.1f}s. New successes={success}, "
        f"failures={failed}, collection_documents={len(final_docs)}"
    )
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
