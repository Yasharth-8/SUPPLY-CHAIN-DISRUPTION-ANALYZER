"""
Multi-Format Document Loader and Parser.
Handles TXT, PDF, DOCX, CSV, XLSX, XML, HTML with zero crashes on empty/damaged files.
Extracts standard metadata headers and numbered paragraphs [P1], [P2], etc.
"""

import os
import re
import csv
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Dict, Any, List, Optional, Tuple

import pymupdf  # PyMuPDF
import docx
import openpyxl
from bs4 import BeautifulSoup

from app.models import TableRef


class ParsedDocument:
    def __init__(
        self,
        doc_id: str,
        path: str,
        title: str = "",
        event_id: str = "NONE",
        source_name: str = "",
        source_type: str = "",
        reliability_tier: int = 2,
        pub_date: Optional[str] = None,
        pub_time: Optional[str] = None,
        country: Optional[str] = None,
        sector: Optional[str] = None,
        language: str = "en",
        paragraphs: Optional[Dict[int, str]] = None,
        raw_text: str = "",
        table_rows: Optional[List[Dict[str, Any]]] = None,
        table_headers: Optional[List[str]] = None,
        is_valid: bool = True,
        error_reason: Optional[str] = None,
    ):
        self.doc_id = doc_id
        self.path = path
        self.title = title
        self.event_id = event_id
        self.source_name = source_name
        self.source_type = source_type
        self.reliability_tier = reliability_tier
        self.pub_date = pub_date
        self.pub_time = pub_time
        self.country = country
        self.sector = sector
        self.language = language
        self.paragraphs = paragraphs or {}
        self.raw_text = raw_text
        self.table_rows = table_rows or []
        self.table_headers = table_headers or []
        self.is_valid = is_valid
        self.error_reason = error_reason

    def to_dict(self) -> Dict[str, Any]:
        return {
            "doc_id": self.doc_id,
            "path": self.path,
            "title": self.title,
            "event_id": self.event_id,
            "source_name": self.source_name,
            "source_type": self.source_type,
            "reliability_tier": self.reliability_tier,
            "pub_date": self.pub_date,
            "pub_time": self.pub_time,
            "country": self.country,
            "sector": self.sector,
            "language": self.language,
            "paragraphs_count": len(self.paragraphs),
            "table_rows_count": len(self.table_rows),
            "is_valid": self.is_valid,
            "error_reason": self.error_reason,
        }


def parse_metadata_and_paragraphs(text: str, default_doc_id: str) -> Dict[str, Any]:
    """
    Parses standard header lines like:
    DOC_ID: ... / DOC ID: ...
    EVENT_ID: ...
    TITLE: ...
    SOURCE_NAME: ... / SOURCE: ...
    SOURCE_TYPE: ...
    RELIABILITY: Tier X or X
    PUB_DATE: ... / DATE: ...
    COUNTRY: ...
    SECTOR: ...
    Then extracts [P1], [P2] paragraphs.
    """
    meta: Dict[str, Any] = {
        "doc_id": default_doc_id,
        "event_id": "NONE",
        "title": "",
        "source_name": "",
        "source_type": "crisis",
        "reliability_tier": 2,
        "pub_date": None,
        "pub_time": None,
        "country": None,
        "sector": "general",
        "language": "en",
        "paragraphs": {},
        "raw_body": "",
    }

    lines = [ln.strip() for ln in text.splitlines()]
    body_lines = []
    in_body = False

    for line in lines:
        if not line:
            if in_body:
                body_lines.append("")
            continue

        if line == "---":
            in_body = True
            continue

        # Check for pipe-delimited header lines like:
        # DOC ID: ATL-1001  |  RELIABILITY: Tier 1  |  DATE: 2025-01-10 09:00
        if "|" in line and any(k in line.upper() for k in ["DOC ID", "RELIABILITY", "SOURCE"]):
            parts = [p.strip() for p in line.split("|")]
            for part in parts:
                _extract_field(part, meta)
            continue

        if not in_body and ":" in line:
            extracted = _extract_field(line, meta)
            if extracted:
                continue

        # If not recognized as metadata, treat as body
        in_body = True
        body_lines.append(line)

    full_body = "\n".join(body_lines).strip()
    meta["raw_body"] = full_body

    # Extract numbered paragraphs: [P1], [P2], etc.
    p_pattern = re.compile(r"\[P(\d+)\]\s*(.*?)(?=\[P\d+\]|\Z)", re.DOTALL)
    matches = p_pattern.findall(full_body)
    if matches:
        for p_num_str, p_content in matches:
            p_num = int(p_num_str)
            meta["paragraphs"][p_num] = p_content.strip()
    else:
        # Fallback: split by double newlines or non-empty lines
        chunks = [c.strip() for c in full_body.split("\n\n") if c.strip()]
        for idx, chunk in enumerate(chunks, start=1):
            meta["paragraphs"][idx] = chunk

    # If title not found in metadata, check first paragraph or header
    if not meta["title"] and body_lines:
        first_line = body_lines[0].strip()
        if not first_line.startswith("[P"):
            meta["title"] = first_line

    return meta


def _extract_field(item: str, meta: Dict[str, Any]) -> bool:
    """Extracts a single key:value metadata field."""
    if ":" not in item:
        return False
    k, v = item.split(":", 1)
    k = k.strip().upper().replace(" ", "_")
    v = v.strip()

    if k in ("DOC_ID", "DOCID", "DOCUMENT_ID"):
        meta["doc_id"] = v
        return True
    elif k in ("EVENT_ID", "EVENTID"):
        meta["event_id"] = v
        return True
    elif k == "TITLE":
        meta["title"] = v
        return True
    elif k in ("SOURCE", "SOURCE_NAME"):
        meta["source_name"] = v
        return True
    elif k in ("SOURCE_TYPE", "SOURCETYPE"):
        meta["source_type"] = v.lower()
        return True
    elif k in ("RELIABILITY", "TIER", "SOURCE_TIER"):
        # Format might be 'Tier 1' or '1'
        m = re.search(r"(\d+)", v)
        if m:
            meta["reliability_tier"] = int(m.group(1))
        return True
    elif k in ("PUB_DATE", "DATE"):
        parts = v.split()
        meta["pub_date"] = parts[0]
        if len(parts) > 1:
            meta["pub_time"] = parts[1]
        return True
    elif k == "PUB_TIME":
        meta["pub_time"] = v
        return True
    elif k == "COUNTRY":
        meta["country"] = v
        return True
    elif k == "SECTOR":
        meta["sector"] = v.lower()
        return True
    elif k == "LANGUAGE":
        meta["language"] = v.lower()
        return True
    return False


class DocumentLoader:
    """Loads and parses any document in docs/."""

    @staticmethod
    def load_document(file_path: str) -> ParsedDocument:
        p = Path(file_path)
        doc_id = p.stem.upper()

        if not p.exists():
            return ParsedDocument(doc_id=doc_id, path=file_path, is_valid=False, error_reason="file_not_found")

        size = p.stat().st_size
        if size == 0:
            return ParsedDocument(doc_id=doc_id, path=file_path, is_valid=False, error_reason="empty_file")

        suffix = p.suffix.lower()

        try:
            if suffix == ".txt":
                return DocumentLoader._load_txt(p, doc_id)
            elif suffix == ".pdf":
                return DocumentLoader._load_pdf(p, doc_id)
            elif suffix == ".docx":
                return DocumentLoader._load_docx(p, doc_id)
            elif suffix == ".csv":
                return DocumentLoader._load_csv(p, doc_id)
            elif suffix == ".xlsx":
                return DocumentLoader._load_xlsx(p, doc_id)
            elif suffix == ".xml":
                return DocumentLoader._load_xml(p, doc_id)
            elif suffix == ".html":
                return DocumentLoader._load_html(p, doc_id)
            else:
                return ParsedDocument(doc_id=doc_id, path=file_path, is_valid=False, error_reason="unsupported_format")
        except Exception as e:
            return ParsedDocument(doc_id=doc_id, path=file_path, is_valid=False, error_reason=f"parse_error: {str(e)}")

    @staticmethod
    def _load_txt(path: Path, doc_id: str) -> ParsedDocument:
        with open(path, "r", encoding="utf-8", errors="replace") as f:
            content = f.read()

        parsed = parse_metadata_and_paragraphs(content, default_doc_id=doc_id)
        return ParsedDocument(
            doc_id=parsed["doc_id"],
            path=str(path),
            title=parsed["title"],
            event_id=parsed["event_id"],
            source_name=parsed["source_name"],
            source_type=parsed["source_type"],
            reliability_tier=parsed["reliability_tier"],
            pub_date=parsed["pub_date"],
            pub_time=parsed["pub_time"],
            country=parsed["country"],
            sector=parsed["sector"],
            language=parsed["language"],
            paragraphs=parsed["paragraphs"],
            raw_text=parsed["raw_body"],
        )

    @staticmethod
    def _load_pdf(path: Path, doc_id: str) -> ParsedDocument:
        doc = pymupdf.open(str(path))
        text_parts = []
        for page in doc:
            text_parts.append(page.get_text("text"))
        doc.close()

        full_text = "\n".join(text_parts)
        parsed = parse_metadata_and_paragraphs(full_text, default_doc_id=doc_id)
        return ParsedDocument(
            doc_id=parsed["doc_id"],
            path=str(path),
            title=parsed["title"],
            event_id=parsed["event_id"],
            source_name=parsed["source_name"],
            source_type=parsed["source_type"],
            reliability_tier=parsed["reliability_tier"],
            pub_date=parsed["pub_date"],
            pub_time=parsed["pub_time"],
            country=parsed["country"],
            sector=parsed["sector"],
            language=parsed["language"],
            paragraphs=parsed["paragraphs"],
            raw_text=parsed["raw_body"],
        )

    @staticmethod
    def _load_docx(path: Path, doc_id: str) -> ParsedDocument:
        doc = docx.Document(str(path))
        # Check header tables for metadata
        header_text_parts = []
        for table in doc.tables:
            for row in table.rows:
                row_items = [c.text.strip() for c in row.cells if c.text.strip()]
                header_text_parts.append(" | ".join(row_items))

        body_parts = [p.text.strip() for p in doc.paragraphs if p.text.strip()]
        combined_text = "\n".join(header_text_parts + ["---"] + body_parts)

        parsed = parse_metadata_and_paragraphs(combined_text, default_doc_id=doc_id)
        return ParsedDocument(
            doc_id=parsed["doc_id"],
            path=str(path),
            title=parsed["title"],
            event_id=parsed["event_id"],
            source_name=parsed["source_name"],
            source_type=parsed["source_type"],
            reliability_tier=parsed["reliability_tier"],
            pub_date=parsed["pub_date"],
            pub_time=parsed["pub_time"],
            country=parsed["country"],
            sector=parsed["sector"],
            language=parsed["language"],
            paragraphs=parsed["paragraphs"],
            raw_text=parsed["raw_body"],
        )

    @staticmethod
    def _load_csv(path: Path, doc_id: str) -> ParsedDocument:
        rows = []
        with open(path, "r", encoding="utf-8", errors="replace") as f:
            reader = csv.DictReader(f)
            headers = reader.fieldnames or []
            for idx, r in enumerate(reader, start=1):
                r["_row_idx"] = idx
                rows.append(r)

        return ParsedDocument(
            doc_id=doc_id,
            path=str(path),
            title=f"Trade Data: {doc_id}",
            event_id="CRX-2027",
            source_type="trade_data",
            reliability_tier=1,
            table_headers=headers,
            table_rows=rows,
        )

    @staticmethod
    def _load_xlsx(path: Path, doc_id: str) -> ParsedDocument:
        wb = openpyxl.load_workbook(str(path), data_only=True)
        ws = wb.active
        all_rows = list(ws.iter_rows(values_only=True))
        if not all_rows:
            return ParsedDocument(doc_id=doc_id, path=str(path), is_valid=False, error_reason="empty_spreadsheet")

        headers = [str(h) if h is not None else f"col_{i}" for i, h in enumerate(all_rows[0])]
        rows = []
        for idx, row_vals in enumerate(all_rows[1:], start=1):
            row_dict = {"_row_idx": idx}
            for h, v in zip(headers, row_vals):
                row_dict[h] = v
            rows.append(row_dict)

        wb.close()
        return ParsedDocument(
            doc_id=doc_id,
            path=str(path),
            title=f"Spreadsheet Data: {doc_id}",
            event_id="CRX-2027",
            source_type="trade_data",
            reliability_tier=1,
            table_headers=headers,
            table_rows=rows,
        )

    @staticmethod
    def _load_xml(path: Path, doc_id: str) -> ParsedDocument:
        tree = ET.parse(str(path))
        root = tree.getroot()

        # Extract elements into structured dictionary
        data_dict: Dict[str, Any] = {}
        for elem in root.iter():
            tag = elem.tag.split("}")[-1]  # remove namespace
            if elem.text and elem.text.strip():
                data_dict[tag] = elem.text.strip()

        # Format into a single table row or paragraphs
        row = {"_row_idx": 1, **data_dict}
        title = data_dict.get("Description", f"Customs Declaration: {doc_id}")
        pub_date = data_dict.get("IssueDate")

        return ParsedDocument(
            doc_id=doc_id,
            path=str(path),
            title=title,
            event_id="CRX-2027",
            source_type="customs_manifest",
            reliability_tier=1,
            pub_date=pub_date,
            table_headers=list(data_dict.keys()),
            table_rows=[row],
        )

    @staticmethod
    def _load_html(path: Path, doc_id: str) -> ParsedDocument:
        with open(path, "r", encoding="utf-8", errors="replace") as f:
            soup = BeautifulSoup(f.read(), "html.parser")

        title = soup.title.string.strip() if soup.title and soup.title.string else f"Advisory Bulletin: {doc_id}"
        paragraphs = {}
        idx = 1
        for p in soup.find_all(["p", "div", "h1", "h2"]):
            txt = p.get_text().strip()
            if txt:
                paragraphs[idx] = txt
                idx += 1

        return ParsedDocument(
            doc_id=doc_id,
            path=str(path),
            title=title,
            event_id="CRX-2027",
            source_type="port_bulletin",
            reliability_tier=1,
            paragraphs=paragraphs,
        )

