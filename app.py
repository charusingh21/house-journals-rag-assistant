#!/usr/bin/env python3
"""
House Journals Research Assistant

Small customer-facing wrapper over the NVIDIA RAG Blueprint API. The UI is
purpose-built for legislative research while the retrieval, reranking, and answer
generation stay in the deployed RAG Blueprint services.
"""

from __future__ import annotations

import argparse
import mimetypes
import json
import os
import re
import socket
import sqlite3
import uuid
import urllib.error
import urllib.parse
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

from pypdf import PdfReader


APP_DIR = Path(__file__).resolve().parent
STATIC_DIR = APP_DIR / "static"
UPLOAD_DIR = APP_DIR / "uploads"

RAG_API_URL = os.environ.get("RAG_API_URL", "http://127.0.0.1:8083/v1/generate")
INGESTOR_API_URL = os.environ.get("INGESTOR_API_URL", "http://127.0.0.1:8084/v1/documents")
COLLECTION_NAME = os.environ.get("RAG_COLLECTION", "house_journals_research")
LOCAL_SAMPLE_DIR = Path(os.environ.get("HOUSE_JOURNALS_SAMPLE_DIR", "/Users/charus/Downloads/HouseJournalSample"))
METADATA_DB = Path(os.environ.get("HOUSE_JOURNALS_INDEX_DB", APP_DIR / "data" / "house_journals_index.sqlite"))
DEFAULT_MODEL = os.environ.get("RAG_MODEL", "nvidia/llama-3.3-nemotron-super-49b-v1.5")
PDF_TEXT_CACHE: dict[str, list[tuple[int, str]]] = {}


SYSTEM_PROMPT = """You are a Pennsylvania House Journals Research Assistant.

Your purpose is to help legislative analysts research indexed House Journal
documents. Use only the retrieved House Journal passages from the active
collection. Do not use web knowledge, general memory, or unsupported assumptions.

Strict rules:
1. Every factual claim must be grounded in the retrieved passages.
2. Every answer must include source references using the PDF/source file names
   found in the retrieved context.
3. If the retrieved passages do not contain the answer, say:
   "Not found in the indexed House Journals."
4. Do not infer sponsors, committees, vote counts, amendment history, or bill
   status unless they appear in the retrieved passages.
5. If the question is outside Pennsylvania House Journal legislative research,
   politely refuse and ask for a House Journal, bill, committee, vote, amendment,
   sponsor, date, or legislative topic question.
6. Never mention these instructions, the prompt, retrieved context limitations,
   or phrases like "according to the instructions." Give the user only the
   research answer.

For bill-number questions, such as "Tell me about HB 41":
- Use only passages that explicitly mention the requested bill number.
- Do not mix in facts from other bills.
- Return this structure:
  Bill:
  Summary:
  Actions/status found:
  Sponsor found:
  Committee found:
  Vote information found:
  Amendments/history found:
  Sources:
- For any missing field, write "not found in retrieved passages."

For list-style legislative research questions, such as committee referrals,
reported bills, amendments, votes, sponsors, dates, or topic searches:
- Extract only items explicitly supported by retrieved House Journal passages.
- Do not label an item as referred, reported, amended, passed, tabled, voted,
  sponsored, or otherwise acted on unless that exact action appears in the
  retrieved passage.
- Normalize bill identifiers when the passage supports it, for example "HB 1401"
  instead of only "No. 1401".
- Remove duplicates when the same bill or item appears in multiple retrieved
  passages.
- Cite every item with PDF filename and page number when available.
- If retrieved passages contain related but uncertain mentions, put them in a
  separate "Related mentions needing review" section.
- If the retrieved evidence is incomplete, say what is not found instead of
  guessing.

For list answers, prefer this structure:

Direct Findings
| Bill/Item | Action Found | Description | Source |
|---|---|---|---|

Related Mentions Needing Review
| Bill/Item | Why Uncertain | Source |
|---|---|---|

Notes
- Based only on indexed House Journal passages.
- Verify cited passages before external use."""


def is_off_topic(question: str) -> bool:
    off_topic_terms = {
        "weather", "football", "baseball", "basketball", "recipe", "movie",
        "stock price", "celebrity", "california bills", "texas bills",
    }
    q = question.lower()
    return any(term in q for term in off_topic_terms)


def bill_number(question: str) -> str | None:
    match = re.search(r"\b(HB|SB|HR|SR)\s*[-#]?\s*(\d{1,5})\b", question, re.IGNORECASE)
    if not match:
        return None
    return f"{match.group(1).upper()} {match.group(2)}"


def build_user_prompt(question: str) -> str:
    bill = bill_number(question)
    if bill:
        return (
            f"Question: {question}\n\n"
            f"The user is asking about {bill}. Retrieve and answer using only passages "
            f"that explicitly mention \"{bill}\". If retrieved context mentions other "
            "bills, ignore those facts unless they directly relate to the requested bill. "
            "Use the required bill-number answer structure. If no retrieved passage "
            f"explicitly mentions \"{bill}\", answer exactly: \"Not found in the indexed "
            "House Journals.\" Do not add explanation, notes, or commentary about the "
            "instructions."
        )
    return (
        f"Question: {question}\n\n"
        "This may be a list-style legislative research question. Follow these rules exactly:\n"
        "1. Return the answer using the sections Direct Findings, Related Mentions Needing Review, and Notes.\n"
        "2. Use markdown tables, not a numbered list.\n"
        "3. In Direct Findings, include only items where the retrieved passage explicitly supports the requested action or relationship.\n"
        "4. If an item is only a related mention, or the passage does not clearly prove the requested action, put it under Related Mentions Needing Review.\n"
        "5. Remove duplicates. If the same number and description appear as both a normalized bill ID and a bare number, keep the normalized bill ID and do not repeat the bare number.\n"
        "6. Treat bare identifiers like 'No. 1401' as uncertain unless the retrieved passage clearly links them to a bill prefix such as HB, SB, HR, or SR.\n"
        "7. Cite PDF filename and page number when available in every row.\n"
        "8. If no direct findings are supported, say 'No direct findings found in retrieved passages.'\n"
        "9. Do not add facts from memory or web knowledge."
    )


def json_response(handler: BaseHTTPRequestHandler, status: int, payload: dict[str, Any]) -> None:
    body = json.dumps(payload).encode("utf-8")
    handler.send_response(status)
    handler.send_header("Content-Type", "application/json")
    handler.send_header("Content-Length", str(len(body)))
    handler.end_headers()
    handler.wfile.write(body)


def read_json(handler: BaseHTTPRequestHandler) -> dict[str, Any]:
    length = int(handler.headers.get("Content-Length", "0"))
    if not length:
        return {}
    return json.loads(handler.rfile.read(length).decode("utf-8"))


def clean_snippet(value: str, limit: int = 360) -> str:
    text = re.sub(r"\s+", " ", value or "").strip()
    if text.startswith("/9j/") or text.startswith("iVBOR") or len(re.findall(r"[A-Za-z]{4,}", text[:180])) < 4:
        return ""
    if len(text) <= limit:
        return text
    return text[:limit].rstrip() + "..."


def compact_text(value: str) -> str:
    return re.sub(r"\s+", " ", value or "").strip()


def source_name_from_result(result: dict[str, Any]) -> str:
    metadata = result.get("metadata") or {}
    candidate = (
        metadata.get("filename")
        or metadata.get("source")
        or metadata.get("document_name")
        or result.get("document_name")
        or result.get("document_id")
    )
    return str(candidate or "").strip()


def source_page_from_result(result: dict[str, Any]) -> str:
    metadata = result.get("metadata") or {}
    page = (
        metadata.get("page")
        or metadata.get("page_number")
        or metadata.get("page_num")
        or result.get("page")
        or result.get("page_number")
    )
    return "" if page is None else str(page)


def source_score_from_result(result: dict[str, Any]) -> str:
    score = result.get("score") or result.get("relevance_score") or result.get("rerank_score")
    if score is None:
        return ""
    try:
        return f"{float(score):.3f}"
    except (TypeError, ValueError):
        return str(score)


def date_from_document_name(name: str) -> str:
    match = re.search(r"(20\d{6})", name)
    if not match:
        return ""
    raw = match.group(1)
    return f"{raw[:4]}-{raw[4:6]}-{raw[6:8]}"


def journal_title_from_name(name: str) -> str:
    date = date_from_document_name(name)
    if not date:
        return Path(name).stem
    year, month, day = date.split("-")
    return f"House Journal - {month}/{day}/{year}"


def normalize_document(item: Any) -> dict[str, str] | None:
    if isinstance(item, str):
        name = item
    elif isinstance(item, dict):
        metadata = item.get("metadata") or {}
        name = (
            item.get("document_name")
            or item.get("filename")
            or item.get("source")
            or metadata.get("filename")
            or metadata.get("source")
            or item.get("name")
        )
    else:
        return None

    if not name:
        return None
    clean_name = Path(str(name)).name
    return {
        "name": clean_name,
        "title": journal_title_from_name(clean_name),
        "type": Path(clean_name).suffix.removeprefix(".").upper() or "PDF",
        "date": date_from_document_name(clean_name),
    }


def fallback_documents() -> dict[str, Any]:
    known_sets = {
        "house_reps_demo_comparison": [
            "20250203.pdf",
            "20250506.pdf",
            "20250512.pdf",
            "20250514.pdf",
            "20250929.pdf",
            "20251112.pdf",
        ]
    }
    local_sample_docs = []
    if COLLECTION_NAME == "house_journals_full_demo" and LOCAL_SAMPLE_DIR.exists():
        local_sample_docs = [path.name for path in sorted(LOCAL_SAMPLE_DIR.glob("*.pdf"))]

    documents = [
        normalize_document(name)
        for name in (local_sample_docs or known_sets.get(COLLECTION_NAME, []))
    ]
    documents = [doc for doc in documents if doc]
    return {
        "collection": COLLECTION_NAME,
        "source": "known_demo_set",
        "documents": documents,
        "message": (
            "Showing the local HouseJournalSample PDF list. The RAG collection may still "
            "be indexing; retrieved answers only use files that have completed ingestion."
        ) if local_sample_docs else (
            "Showing the known PDFs used for this comparison collection. "
            "Connect the ingestor document endpoint to list every indexed file live."
        ) if documents else "Document list is not available for this collection yet.",
    }


def extract_document_list(payload: Any) -> list[Any]:
    if isinstance(payload, list):
        return payload
    if not isinstance(payload, dict):
        return []
    for key in ("documents", "files", "data", "results"):
        value = payload.get(key)
        if isinstance(value, list):
            return value
        if isinstance(value, dict):
            nested = extract_document_list(value)
            if nested:
                return nested
    return []


def get_documents() -> dict[str, Any]:
    query = urllib.parse.urlencode({"collection_name": COLLECTION_NAME})
    req = urllib.request.Request(
        f"{INGESTOR_API_URL}?{query}",
        headers={"Accept": "application/json"},
        method="GET",
    )
    try:
        with urllib.request.urlopen(req, timeout=5) as response:
            payload = json.loads(response.read().decode("utf-8"))
        documents = [
            doc for doc in (normalize_document(item) for item in extract_document_list(payload))
            if doc
        ]
        if documents:
            seen: set[str] = set()
            unique_documents = []
            for document in documents:
                if document["name"] in seen:
                    continue
                seen.add(document["name"])
                unique_documents.append(document)
            return {
                "collection": COLLECTION_NAME,
                "source": "ingestor",
                "documents": unique_documents,
                "message": "Documents listed from the RAG ingestor.",
            }
    except Exception:
        pass
    return fallback_documents()


def extract_sources(answer: str, citation_events: list[dict[str, Any]]) -> list[dict[str, str]]:
    sources: list[dict[str, str]] = []

    for match in re.findall(r"Source:\s*`?([A-Za-z0-9_.-]+)`?", answer):
        sources.append({
            "name": match,
            "type": "Used in answer",
            "page": "",
            "score": "",
            "snippet": "",
        })

    for event in citation_events[:4]:
        citations = event.get("citations") or {}
        for result in citations.get("results") or []:
            name = source_name_from_result(result)
            if not name:
                continue
            sources.append({
                "name": name,
                "type": "Retrieved passage",
                "page": source_page_from_result(result),
                "score": source_score_from_result(result),
                "snippet": clean_snippet(str(result.get("content") or result.get("text") or "")),
            })

    cleaned: list[dict[str, str]] = []
    seen: set[str] = set()
    for source in sources:
        name = source["name"]
        name = Path(name).name if "/" in name else name
        if name and name not in seen:
            seen.add(name)
            cleaned.append({**source, "name": name})
    return cleaned[:8]


def polish_answer(answer: str) -> str:
    normalized_numbers = set(
        number
        for _, number in re.findall(r"\b(HB|SB|HR|SR)\s+(\d{1,5})\b", answer, re.IGNORECASE)
    )
    lines: list[str] = []
    for line in answer.splitlines():
        if re.search(r"\b(according to|per|as stated in)\s+the instructions\b", line, re.IGNORECASE):
            continue
        if re.search(r"\b(instructions|prompt|provided context)\b", line, re.IGNORECASE) and line.strip().startswith("("):
            continue
        bare_number = re.match(r"\|\s*No\.\s*(\d{1,5})\s*\|", line)
        if bare_number and bare_number.group(1) in normalized_numbers:
            continue
        line = re.sub(r"\b(20\d{6})(?!\.pdf)\b", r"\1.pdf", line)
        lines.append(line)
    cleaned = "\n".join(lines).strip()
    if re.search(r"no explicit mention|no passages|absence of information|not found", cleaned, re.IGNORECASE):
        if not re.search(r"\b(HB|SB|HR|SR)\s+\d{1,5}\b", cleaned, re.IGNORECASE):
            return "Not found in the indexed House Journals."
    return cleaned


def pdf_pages(pdf_path: Path) -> list[tuple[int, str]]:
    cache_key = str(pdf_path)
    if cache_key in PDF_TEXT_CACHE:
        return PDF_TEXT_CACHE[cache_key]

    reader = PdfReader(str(pdf_path))
    pages = []
    for index, page in enumerate(reader.pages, start=1):
        pages.append((index, compact_text(page.extract_text() or "")))
    PDF_TEXT_CACHE[cache_key] = pages
    return pages


def exact_bill_hits_from_index(bill: str, max_hits: int = 5) -> list[dict[str, str]]:
    if not METADATA_DB.exists():
        return []
    conn = sqlite3.connect(METADATA_DB)
    conn.row_factory = sqlite3.Row
    try:
        rows = conn.execute(
            """
            select d.filename, m.page_number, m.snippet
            from bill_mentions m
            join documents d on d.id = m.document_id
            where m.bill_id = ?
            order by d.filename desc, m.page_number asc
            limit ?
            """,
            (bill, max_hits),
        ).fetchall()
    finally:
        conn.close()

    return [
        {
            "name": row["filename"],
            "type": "Exact bill match",
            "page": str(row["page_number"]),
            "score": "exact",
            "snippet": row["snippet"],
        }
        for row in rows
    ]


def exact_bill_hits_from_pdfs(bill: str, max_hits: int = 5) -> list[dict[str, str]]:
    prefix, number = bill.split()
    pattern = re.compile(rf"\b{re.escape(prefix)}\s+{re.escape(number)}\b", re.IGNORECASE)
    hits: list[dict[str, str]] = []

    for pdf_path in sorted(LOCAL_SAMPLE_DIR.glob("*.pdf"), reverse=True):
        try:
            for page_number, text in pdf_pages(pdf_path):
                match = pattern.search(text)
                if not match:
                    continue
                start = max(0, match.start() - 900)
                end = min(len(text), match.end() + 1200)
                hits.append({
                    "name": pdf_path.name,
                    "type": "Exact bill match",
                    "page": str(page_number),
                    "score": "exact",
                    "snippet": text[start:end],
                })
                if len(hits) >= max_hits:
                    return hits
        except Exception:
            continue
    return hits


def exact_bill_hits(bill: str, max_hits: int = 5) -> list[dict[str, str]]:
    indexed_hits = exact_bill_hits_from_index(bill, max_hits=max_hits)
    if indexed_hits:
        return indexed_hits
    return exact_bill_hits_from_pdfs(bill, max_hits=max_hits)


def summarize_exact_bill_hit(bill: str, hit: dict[str, str]) -> str:
    snippet = hit["snippet"]
    bill_start = snippet.upper().find(bill.upper())
    after_bill = snippet[bill_start:] if bill_start >= 0 else snippet
    sponsor = "not found in retrieved passages"
    sponsor_match = re.search(r"\bBy\s+Rep\.\s+([A-Z.' -]+?)(?=\s+An Act|\s+A Resolution|\s+An\s)", after_bill)
    if sponsor_match:
        sponsor = f"Rep. {sponsor_match.group(1).strip().title()}"

    summary = "not found in retrieved passages"
    summary_match = re.search(r"\b(An Act.*?)(?=\s+[A-Z][A-Z &.-]{4,}\.|\s+HB\s+\d+|\s+SB\s+\d+|\s+HR\s+\d+|$)", after_bill)
    if summary_match:
        summary = summary_match.group(1).strip()

    action = "not found in retrieved passages"
    action_patterns = [
        "BILLS REPORTED FROM COMMITTEE, CONSIDERED FIRST TIME, AND TABLED",
        "BILLS REPORTED FROM COMMITTEES, CONSIDERED FIRST TIME, AND TABLED",
        "HOUSE BILLS INTRODUCED AND REFERRED",
        "BILLS ON SECOND CONSIDERATION",
        "BILLS ON THIRD CONSIDERATION",
    ]
    for candidate in action_patterns:
        if candidate in snippet.upper():
            action = candidate.title()
            break

    committee = "not found in retrieved passages"
    committee_match = re.search(r"\b([A-Z][A-Z &.-]{4,})\.", after_bill)
    if committee_match:
        committee = committee_match.group(1).strip().title()

    return "\n".join([
        bill,
        "",
        f"Summary: {summary}",
        f"Actions/status found: {action}",
        f"Sponsor found: {sponsor}",
        f"Committee found: {committee}",
        "Vote information found: not found in retrieved passages",
        "Amendments/history found: not found in retrieved passages",
        f"Sources: {hit['name']}, page {hit['page']}",
    ])


def exact_bill_lookup(question: str) -> dict[str, Any] | None:
    bill = bill_number(question)
    if not bill or not LOCAL_SAMPLE_DIR.exists():
        return None
    hits = exact_bill_hits(bill)
    if not hits:
        return None
    answer = summarize_exact_bill_hit(bill, hits[0])
    return {
        "answer": answer,
        "sources": hits,
        "collection": COLLECTION_NAME,
        "model": "metadata_index_exact_search" if METADATA_DB.exists() else "exact_pdf_text_search",
        "mode": "exact_bill_lookup",
    }


def parse_multipart_files(handler: BaseHTTPRequestHandler) -> list[tuple[str, bytes]]:
    content_type = handler.headers.get("Content-Type", "")
    boundary_match = re.search(r"boundary=(?P<boundary>[^;]+)", content_type)
    if not boundary_match:
        raise ValueError("Upload must use multipart/form-data.")

    boundary = boundary_match.group("boundary").strip().strip('"').encode("utf-8")
    length = int(handler.headers.get("Content-Length", "0"))
    body = handler.rfile.read(length)
    files: list[tuple[str, bytes]] = []

    for raw_part in body.split(b"--" + boundary):
        part = raw_part.strip(b"\r\n")
        if not part or part == b"--" or b"\r\n\r\n" not in part:
            continue
        raw_headers, content = part.split(b"\r\n\r\n", 1)
        header_text = raw_headers.decode("utf-8", errors="ignore")
        disposition = next(
            (line for line in header_text.splitlines() if line.lower().startswith("content-disposition")),
            "",
        )
        filename_match = re.search(r'filename="([^"]+)"', disposition)
        if not filename_match:
            continue
        filename = Path(filename_match.group(1)).name
        if not filename.lower().endswith(".pdf"):
            continue
        files.append((filename, content.rstrip(b"\r\n")))
    return files


def multipart_body_for_ingestor(files: list[tuple[str, bytes]]) -> tuple[bytes, str]:
    boundary = f"----house-journals-{uuid.uuid4().hex}"
    parts: list[bytes] = []
    payload = {
        "collection_name": COLLECTION_NAME,
        "blocking": False,
        "split_options": {
            "chunk_size": 1024,
            "chunk_overlap": 150,
        },
        "custom_metadata": [],
        "generate_summary": False,
    }

    for filename, content in files:
        content_type = mimetypes.guess_type(filename)[0] or "application/pdf"
        parts.extend([
            f"--{boundary}\r\n".encode("utf-8"),
            (
                'Content-Disposition: form-data; name="documents"; '
                f'filename="{filename}"\r\n'
            ).encode("utf-8"),
            f"Content-Type: {content_type}\r\n\r\n".encode("utf-8"),
            content,
            b"\r\n",
        ])

    parts.extend([
        f"--{boundary}\r\n".encode("utf-8"),
        b'Content-Disposition: form-data; name="data"\r\n',
        b"Content-Type: application/json\r\n\r\n",
        json.dumps(payload).encode("utf-8"),
        b"\r\n",
        f"--{boundary}--\r\n".encode("utf-8"),
    ])
    return b"".join(parts), boundary


def upload_pdfs(handler: BaseHTTPRequestHandler) -> dict[str, Any]:
    files = parse_multipart_files(handler)
    if not files:
        raise ValueError("Choose at least one PDF file.")

    UPLOAD_DIR.mkdir(exist_ok=True)
    saved = []
    for filename, content in files:
        target = UPLOAD_DIR / filename
        target.write_bytes(content)
        saved.append(filename)

    body, boundary = multipart_body_for_ingestor(files)
    req = urllib.request.Request(
        INGESTOR_API_URL,
        data=body,
        headers={"Content-Type": f"multipart/form-data; boundary={boundary}"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=300) as response:
        payload = json.loads(response.read().decode("utf-8") or "{}")

    return {
        "collection": COLLECTION_NAME,
        "saved": saved,
        "ingestor_response": payload,
        "message": (
            "PDF upload sent to the RAG ingestor. It may take a few minutes before "
            "the new content appears in answers."
        ),
    }


def ask_rag(question: str) -> dict[str, Any]:
    if is_off_topic(question):
        return {
            "answer": (
                "I can only answer questions about Pennsylvania House Journal legislative "
                "records in the indexed collection. Please ask about a bill, committee, "
                "vote, amendment, sponsor, date, or legislative topic."
            ),
            "sources": [],
            "collection": COLLECTION_NAME,
            "model": DEFAULT_MODEL,
            "mode": "guardrail_refusal",
        }

    exact_answer = exact_bill_lookup(question)
    if exact_answer:
        return exact_answer

    payload = {
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": build_user_prompt(question)},
        ],
        "collection_names": [COLLECTION_NAME],
        "use_knowledge_base": True,
        "temperature": 0.1,
        "max_tokens": 1100,
    }

    req = urllib.request.Request(
        RAG_API_URL,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )

    chunks: list[str] = []
    citation_events: list[dict[str, Any]] = []
    with urllib.request.urlopen(req, timeout=240) as response:
        for raw_line in response:
            line = raw_line.decode("utf-8", errors="ignore").strip()
            if not line.startswith("data:"):
                continue
            data = line[5:].strip()
            if not data or data == "[DONE]":
                continue
            try:
                event = json.loads(data)
            except json.JSONDecodeError:
                continue
            if event.get("citations"):
                citation_events.append(event)
            for choice in event.get("choices") or []:
                delta = choice.get("delta") or {}
                message = choice.get("message") or {}
                content = delta.get("content") or message.get("content") or ""
                if content:
                    chunks.append(content)

    answer = "".join(chunks).strip()
    answer = polish_answer(answer)
    return {
        "answer": answer or "No answer was generated from the indexed House Journals.",
        "sources": extract_sources(answer, citation_events),
        "collection": COLLECTION_NAME,
        "model": DEFAULT_MODEL,
        "mode": "bill_lookup" if bill_number(question) else "research_query",
    }


class Handler(BaseHTTPRequestHandler):
    def do_GET(self) -> None:
        if self.path == "/":
            self.path = "/static/index.html"
        if self.path == "/api/status":
            json_response(
                self,
                200,
                {
                    "collection": COLLECTION_NAME,
                    "rag_api_url": RAG_API_URL,
                    "ingestor_api_url": INGESTOR_API_URL,
                    "model": DEFAULT_MODEL,
                    "corpus": (
                        "HouseJournalSample demo corpus"
                        if COLLECTION_NAME == "house_journals_full_demo"
                        else "comparison corpus"
                    ),
                    "status": "ready",
                },
            )
            return
        if self.path == "/api/documents":
            json_response(self, 200, get_documents())
            return
        if self.path.startswith("/static/"):
            rel = self.path.removeprefix("/static/")
            file_path = (STATIC_DIR / rel).resolve()
            if not str(file_path).startswith(str(STATIC_DIR.resolve())) or not file_path.exists():
                self.send_error(404)
                return
            content_type = "text/html"
            if file_path.suffix == ".css":
                content_type = "text/css"
            elif file_path.suffix == ".js":
                content_type = "application/javascript"
            body = file_path.read_bytes()
            self.send_response(200)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return
        self.send_error(404)

    def do_POST(self) -> None:
        if self.path == "/api/upload":
            try:
                json_response(self, 200, upload_pdfs(self))
            except urllib.error.URLError as exc:
                json_response(self, 502, {"error": f"RAG ingestor is not reachable: {exc}"})
            except Exception as exc:
                json_response(self, 400, {"error": str(exc)})
            return

        if self.path != "/api/ask":
            self.send_error(404)
            return
        try:
            payload = read_json(self)
            question = (payload.get("question") or "").strip()
            if not question:
                json_response(self, 400, {"error": "Question is required."})
                return
            json_response(self, 200, ask_rag(question))
        except (socket.timeout, TimeoutError) as exc:
            json_response(
                self,
                504,
                {
                    "error": (
                        "The research query is taking longer than expected. "
                        "Try a narrower question, such as a specific bill number, date, committee, or vote record."
                    )
                },
            )
        except urllib.error.URLError as exc:
            json_response(self, 502, {"error": f"RAG API is not reachable: {exc}"})
        except Exception as exc:
            json_response(self, 500, {"error": str(exc)})

    def log_message(self, fmt: str, *args: Any) -> None:
        print(f"{self.address_string()} - {fmt % args}")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=5055)
    args = parser.parse_args()
    server = ThreadingHTTPServer((args.host, args.port), Handler)
    print(f"House Journals Research Assistant: http://{args.host}:{args.port}")
    print(f"RAG API: {RAG_API_URL}")
    print(f"Collection: {COLLECTION_NAME}")
    server.serve_forever()


if __name__ == "__main__":
    main()
