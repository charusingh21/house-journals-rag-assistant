#!/usr/bin/env python3
from __future__ import annotations

import argparse
import re
import sqlite3
from pathlib import Path

from pypdf import PdfReader


BILL_RE = re.compile(r"\b(HB|SB|HR|SR)\s+(\d{1,5})\b", re.IGNORECASE)


def compact_text(value: str) -> str:
    return re.sub(r"\s+", " ", value or "").strip()


def journal_date(filename: str) -> str:
    match = re.search(r"(20\d{6})", filename)
    if not match:
        return ""
    raw = match.group(1)
    return f"{raw[:4]}-{raw[4:6]}-{raw[6:8]}"


def snippet_for(text: str, start: int, end: int) -> str:
    return text[max(0, start - 900): min(len(text), end + 1200)]


def init_db(conn: sqlite3.Connection) -> None:
    conn.executescript(
        """
        drop table if exists bill_mentions;
        drop table if exists pages;
        drop table if exists documents;

        create table documents (
            id integer primary key,
            filename text not null unique,
            journal_date text,
            year integer
        );

        create table pages (
            id integer primary key,
            document_id integer not null,
            page_number integer not null,
            text text not null,
            unique(document_id, page_number),
            foreign key(document_id) references documents(id)
        );

        create table bill_mentions (
            id integer primary key,
            bill_id text not null,
            document_id integer not null,
            page_id integer not null,
            page_number integer not null,
            snippet text not null,
            foreign key(document_id) references documents(id),
            foreign key(page_id) references pages(id)
        );

        create index idx_documents_filename on documents(filename);
        create index idx_documents_year on documents(year);
        create index idx_bill_mentions_bill_id on bill_mentions(bill_id);
        create index idx_bill_mentions_doc_page on bill_mentions(document_id, page_number);
        """
    )


def index_pdf(conn: sqlite3.Connection, pdf_path: Path) -> tuple[int, int]:
    date = journal_date(pdf_path.name)
    year = int(date[:4]) if date else None
    cursor = conn.execute(
        "insert into documents(filename, journal_date, year) values (?, ?, ?)",
        (pdf_path.name, date, year),
    )
    document_id = cursor.lastrowid
    page_count = 0
    mention_count = 0

    reader = PdfReader(str(pdf_path))
    for page_number, page in enumerate(reader.pages, start=1):
        text = compact_text(page.extract_text() or "")
        cursor = conn.execute(
            "insert into pages(document_id, page_number, text) values (?, ?, ?)",
            (document_id, page_number, text),
        )
        page_id = cursor.lastrowid
        page_count += 1

        for match in BILL_RE.finditer(text):
            bill_id = f"{match.group(1).upper()} {match.group(2)}"
            conn.execute(
                """
                insert into bill_mentions(bill_id, document_id, page_id, page_number, snippet)
                values (?, ?, ?, ?, ?)
                """,
                (bill_id, document_id, page_id, page_number, snippet_for(text, match.start(), match.end())),
            )
            mention_count += 1

    return page_count, mention_count


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--pdf-dir", required=True)
    parser.add_argument("--db", required=True)
    parser.add_argument(
        "--from-date",
        default="",
        help="Include PDFs with date-like filenames on or after YYYYMMDD.",
    )
    parser.add_argument(
        "--to-date",
        default="",
        help="Include PDFs with date-like filenames on or before YYYYMMDD.",
    )
    parser.add_argument(
        "--latest",
        type=int,
        default=0,
        help="Index only the latest N PDFs by date-like filename. Use 0 for all PDFs.",
    )
    args = parser.parse_args()

    pdf_dir = Path(args.pdf_dir)
    db_path = Path(args.db)
    db_path.parent.mkdir(parents=True, exist_ok=True)

    conn = sqlite3.connect(db_path)
    init_db(conn)

    total_pages = 0
    total_mentions = 0
    pdfs = sorted(pdf_dir.glob("*.pdf"))
    if args.from_date or args.to_date:
        start = args.from_date or "00000000"
        end = args.to_date or "99999999"
        pdfs = [
            pdf for pdf in pdfs
            if (date_match := re.search(r"(20\d{6})", pdf.name)) and start <= date_match.group(1) <= end
        ]
        print(f"Indexing date range {start} to {end}: {len(pdfs)} PDFs from {pdf_dir}", flush=True)
    if args.latest > 0:
        pdfs = pdfs[-args.latest:]
        print(f"Indexing latest {len(pdfs)} PDFs from {pdf_dir}", flush=True)
    for index, pdf in enumerate(pdfs, start=1):
        print(f"Indexing {index}/{len(pdfs)}: {pdf.name}", flush=True)
        pages, mentions = index_pdf(conn, pdf)
        total_pages += pages
        total_mentions += mentions
        if index % 10 == 0 or index == len(pdfs):
            conn.commit()
            print(f"Indexed {index}/{len(pdfs)} PDFs, {total_pages} pages, {total_mentions} bill mentions", flush=True)

    conn.commit()
    conn.close()
    print(f"Done: {db_path}", flush=True)


if __name__ == "__main__":
    main()
