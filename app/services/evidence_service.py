"""
Evidence Service: Card Generation, Source Enrichment, Dedup, and Coverage Matrix.
Generates compact EvidenceCard models from ParsedDocuments.
"""

import hashlib
import re
from typing import Dict, List, Optional, Set, Tuple
from rapidfuzz import fuzz

from app.models import EvidenceCard, TableRef, ExcludedDocument
from app.services.document_loader import ParsedDocument
from app.constants import PROMPT_INJECTION_PATTERNS
from app.vocabularies import Country, Sector, Commodity, TimeHorizon


class EvidenceService:
    def __init__(self):
        self.evidence_cards: Dict[str, EvidenceCard] = {}
        self.doc_to_cards: Dict[str, List[str]] = {}
        self.text_hashes: Dict[str, str] = {}  # text_hash -> first_doc_id (for dedup/independence)

    def process_document(
        self,
        doc: ParsedDocument,
        as_of_date: Optional[str] = None,
        event_id: Optional[str] = None,
        reference_region: Optional[List[str]] = None,
        reference_sectors: Optional[List[str]] = None,
        is_hypothetical: bool = False,
    ) -> Tuple[List[EvidenceCard], Optional[ExcludedDocument]]:
        """
        Applies Gatekeeper exclusion filters and generates EvidenceCards if approved.
        Returns (list of cards, exclusion_record if excluded).
        """
        # Filter 1: Check document validity
        if not doc.is_valid:
            return [], ExcludedDocument(doc_id=doc.doc_id, reason=doc.error_reason or "invalid_file")

        # Filter 2: Post-cutoff check
        if as_of_date and doc.pub_date:
            if doc.pub_date > as_of_date:
                return [], ExcludedDocument(
                    doc_id=doc.doc_id,
                    reason=f"post-cutoff: published {doc.pub_date} after as-of date {as_of_date}"
                )

        # Filter 3: Topic / Sector Relevance Check
        # Generic ontology check: If inquiry specifies reference sectors, any crisis document whose sector
        # has ZERO overlap with the inquiry sectors and mentions none of the inquiry's reference entities is excluded.
        if reference_sectors and doc.source_type == "crisis":
            doc_sec_parent = self._normalize_sector(doc.sector) or "general"
            if "." in doc_sec_parent:
                doc_sec_parent = doc_sec_parent.split(".")[0]

            inquiry_parents = {s.split(".")[0] if "." in s else s for s in reference_sectors}
            
            # Check if document sector matches any inquiry sector
            sector_overlap = (doc_sec_parent in inquiry_parents) or (doc_sec_parent == "general")
            
            # Check if document text mentions any target country using full country names & word boundaries
            COUNTRY_NAME_SYNONYMS = {
                "IN": ["india", "indian"],
                "CN": ["china", "chinese"],
                "BR": ["brazil", "brazilian"],
                "DE": ["germany", "german"],
                "US": ["united states", "usa", "america", "american"],
                "RU": ["russia", "russian"],
                "IR": ["iran", "iranian"],
                "AE": ["uae", "emirates", "abu dhabi", "dubai"],
                "NL": ["netherlands", "dutch", "rotterdam"],
                "SA": ["saudi", "saudi arabia"],
                "TR": ["turkey", "türkiye", "turkish"],
                "SG": ["singapore"],
                "GB": ["united kingdom", "britain", "british", "uk"],
                "JP": ["japan", "japanese"],
                "KR": ["korea", "south korea", "korean"],
            }
            target_names = set()
            if reference_region:
                for r in reference_region:
                    r_val = r.value if hasattr(r, "value") else str(r)
                    r_clean = r_val.replace("Country.", "").upper()
                    target_names.update(COUNTRY_NAME_SYNONYMS.get(r_clean, [r_clean.lower()]))

            doc_text_lower = (doc.title + " " + doc.raw_text).lower()
            entity_overlap = any(re.search(rf"\b{re.escape(name)}\b", doc_text_lower) for name in target_names)

            if not sector_overlap and not entity_overlap:
                return [], ExcludedDocument(
                    doc_id=doc.doc_id,
                    reason=f"topic_mismatch: document sector '{doc_sec_parent}' ({doc.title}) has no topical overlap with inquiry sectors {list(inquiry_parents)}"
                )

        # Filter 3b: Geographic Scope Check
        # If inquiry targets specific countries and does not request GLOBAL, exclude crisis or profile documents
        # from disjoint foreign countries that contain zero references to the inquiry's target entities.
        if reference_region and doc.country and doc.country.upper() not in ("GLOBAL", "UNKNOWN", ""):
            ref_clean = {
                (r.value if hasattr(r, "value") else str(r)).replace("Country.", "").upper()
                for r in reference_region
            }
            doc_c = doc.country.upper()
            if "GLOBAL" not in ref_clean and doc_c not in ref_clean:
                COUNTRY_SYNONYMS_LOCAL = {
                    "IN": ["india", "indian", "mumbai", "bombay", "jnpt", "nhava", "mundra", "kandla", "wdfc"],
                    "CN": ["china", "chinese"],
                    "BR": ["brazil", "brazilian"],
                    "DE": ["germany", "german"],
                    "US": ["united states", "usa", "america", "american"],
                    "RU": ["russia", "russian"],
                    "IR": ["iran", "iranian"],
                    "AE": ["uae", "emirates", "abu dhabi", "dubai", "fujairah", "adcop"],
                    "NL": ["netherlands", "dutch", "rotterdam"],
                    "SA": ["saudi", "saudi arabia"],
                }
                target_names_local = set()
                for rc in ref_clean:
                    target_names_local.update(COUNTRY_SYNONYMS_LOCAL.get(rc, [rc.lower()]))

                doc_text_lower = (doc.title + " " + doc.raw_text).lower()
                has_target_mention = any(re.search(rf"\b{re.escape(name)}\b", doc_text_lower) for name in target_names_local)

                if not has_target_mention:
                    return [], ExcludedDocument(
                        doc_id=doc.doc_id,
                        reason=f"geographic_mismatch: document country '{doc_c}' ({doc.title}) does not involve inquiry countries {list(ref_clean)}"
                    )

        # Filter 4: Wrong event check
        if not is_hypothetical:
            if event_id and doc.event_id not in ("NONE", event_id):
                return [], ExcludedDocument(
                    doc_id=doc.doc_id,
                    reason=f"wrong_event: doc event_id '{doc.event_id}' does not match case '{event_id}'"
                )
        else:
            # For hypothetical, if reference region/sectors provided, filter irrelevant ones
            if reference_region and doc.country:
                norm_c = self._normalize_country(doc.country)
                if norm_c and norm_c not in reference_region and doc.event_id != "NONE":
                    return [], ExcludedDocument(
                        doc_id=doc.doc_id,
                        reason=f"hypothetical_region_mismatch: country '{doc.country}' outside reference region"
                    )

        # Filter 4: Prompt injection check
        combined_text = doc.raw_text + " " + " ".join(doc.paragraphs.values())
        for pat in PROMPT_INJECTION_PATTERNS:
            if pat.search(combined_text):
                return [], ExcludedDocument(
                    doc_id=doc.doc_id,
                    reason="prompt_injection_pattern_detected"
                )

        # Classify source category
        source_category = self._infer_source_category(doc.source_name, doc.source_type, doc.reliability_tier)

        # Check sentiment_only flag (Tier 4)
        sentiment_only = (doc.reliability_tier >= 4)

        # Check retraction / post-cutoff trap text in content
        retracted = False
        if "RETRACTED" in combined_text.upper() or "CORRECTION:" in combined_text.upper():
            retracted = True

        # Normalized country & sector
        norm_country = self._normalize_country(doc.country)
        norm_sector = self._normalize_sector(doc.sector)

        cards: List[EvidenceCard] = []

        # Generate cards for paragraphs
        if doc.paragraphs:
            for p_num, p_text in doc.paragraphs.items():
                if not p_text.strip():
                    continue

                card_id = f"EV-{doc.doc_id}-P{p_num}"
                p_hash = hashlib.sha256(p_text.encode("utf-8")).hexdigest()[:12]

                # Check independence / deduplication
                independent = True
                if p_hash in self.text_hashes and self.text_hashes[p_hash] != doc.doc_id:
                    independent = False
                else:
                    self.text_hashes[p_hash] = doc.doc_id

                primary = (doc.reliability_tier in (1, 2) and source_category in ("official", "corporate", "journalistic"))

                card = EvidenceCard(
                    evidence_id=card_id,
                    doc_id=doc.doc_id,
                    paragraph=p_num,
                    quote=p_text[:280] + ("..." if len(p_text) > 280 else ""),
                    table_ref=None,
                    title=doc.title or f"Doc {doc.doc_id}",
                    published_at=f"{doc.pub_date} {doc.pub_time}".strip() if doc.pub_date else None,
                    source_tier=doc.reliability_tier,
                    source_type=doc.source_type,
                    source_category=source_category,
                    primary_reporting=primary,
                    independent=independent,
                    sentiment_only=sentiment_only,
                    retracted=retracted,
                    event_id=doc.event_id,
                    country=norm_country,
                    sector=norm_sector,
                    hash=p_hash,
                )
                cards.append(card)
                self.evidence_cards[card.evidence_id] = card

        # Generate cards for trade table rows
        elif doc.table_rows:
            for r in doc.table_rows:
                r_idx = r.get("_row_idx", 1)
                card_id = f"EV-{doc.doc_id}-R{r_idx}"
                r_summary = ", ".join(f"{k}: {v}" for k, v in r.items() if not k.startswith("_"))
                r_hash = hashlib.sha256(r_summary.encode("utf-8")).hexdigest()[:12]

                first_col = doc.table_headers[0] if doc.table_headers else "data"
                card = EvidenceCard(
                    evidence_id=card_id,
                    doc_id=doc.doc_id,
                    paragraph=None,
                    quote=r_summary[:280],
                    table_ref=TableRef(doc_id=doc.doc_id, row=r_idx, column=first_col),
                    title=doc.title or f"Table {doc.doc_id}",
                    published_at=doc.pub_date,
                    source_tier=doc.reliability_tier,
                    source_type=doc.source_type,
                    source_category="official",
                    primary_reporting=True,
                    independent=True,
                    sentiment_only=False,
                    retracted=False,
                    event_id=doc.event_id,
                    country=norm_country,
                    sector=norm_sector or "logistics.shipping",
                    hash=r_hash,
                )
                cards.append(card)
                self.evidence_cards[card.evidence_id] = card

        if cards:
            self.doc_to_cards[doc.doc_id] = [c.evidence_id for c in cards]

        return cards, None

    def get_card(self, evidence_id: str) -> Optional[EvidenceCard]:
        return self.evidence_cards.get(evidence_id)

    def compute_coverage_matrix(self, cards: List[EvidenceCard]) -> Dict[str, bool]:
        """
        Builds a coverage dictionary mapping '{country}/{sector}/{time_horizon}' to bool.
        """
        matrix: Dict[str, bool] = {}
        for card in cards:
            c = card.country or "GLOBAL"
            s = card.sector or "general"
            key = f"{c}/{s}"
            matrix[key] = True
        return matrix

    @staticmethod
    def _infer_source_category(source_name: str, source_type: str, tier: int) -> str:
        s_lower = (source_name + " " + source_type).lower()
        if tier == 1 or any(w in s_lower for w in ["ministry", "authority", "commission", "customs", "port of", "opec"]):
            return "official"
        if any(w in s_lower for w in ["company", "corp", "nioc", "petrobras", "aramco", "clarksons"]):
            return "corporate"
        if tier == 2 or any(w in s_lower for w in ["reuters", "bloomberg", "platts", "journal", "times", "wire"]):
            return "journalistic"
        if tier == 4 or any(w in s_lower for w in ["telegram", "blog", "whisper", "scoop", "roar"]):
            return "social"
        return "journalistic"

    @staticmethod
    def _normalize_country(country_str: Optional[str]) -> Optional[str]:
        if not country_str:
            return None
        c_clean = country_str.strip().upper()
        # Direct ISO match
        if c_clean in Country.__members__:
            return c_clean

        mapping = {
            "UNITED STATES": "US", "USA": "US", "UNITED STATES OF AMERICA": "US",
            "CHINA": "CN", "PEOPLE'S REPUBLIC OF CHINA": "CN", "PRC": "CN",
            "RUSSIAN FEDERATION": "RU", "RUSSIA": "RU",
            "IRAN": "IR", "ISLAMIC REPUBLIC OF IRAN": "IR",
            "UNITED ARAB EMIRATES": "AE", "UAE": "AE",
            "TURKEY": "TR", "TÜRKIYE": "TR", "REPUBLIC OF TURKEY": "TR",
            "BRAZIL": "BR", "FEDERATIVE REPUBLIC OF BRAZIL": "BR",
            "INDIA": "IN", "REPUBLIC OF INDIA": "IN",
            "NETHERLANDS": "NL", "THE NETHERLANDS": "NL",
            "GERMANY": "DE", "FEDERAL REPUBLIC OF GERMANY": "DE",
            "SAUDI ARABIA": "SA", "KINGDOM OF SAUDI ARABIA": "SA",
            "SINGAPORE": "SG", "REPUBLIC OF SINGAPORE": "SG",
            "UNITED KINGDOM": "GB", "UK": "GB",
            "EUROPEAN UNION": "EU", "EU": "EU",
            "JAPAN": "JP", "SOUTH KOREA": "KR", "KOREA": "KR",
            "AUSTRALIA": "AU", "EGYPT": "EG", "YEMEN": "YE",
        }
        return mapping.get(c_clean)

    @staticmethod
    def _normalize_sector(sector_str: Optional[str]) -> Optional[str]:
        if not sector_str:
            return None
        s_clean = sector_str.strip().lower()
        mapping = {
            "energy": "energy.upstream",
            "oil": "energy.upstream",
            "refining": "energy.refining",
            "shipping": "logistics.shipping",
            "maritime": "logistics.shipping",
            "ports": "logistics.ports",
            "agriculture": "agriculture.farming",
            "fertilizer": "chemicals.fertilizer",
            "petrochemicals": "chemicals.petrochemicals",
            "automotive": "automotive",
            "electronics": "electronics",
            "mining": "mining",
            "bunkering": "energy.refining",
            "geopolitics": "logistics.shipping",
        }
        return mapping.get(s_clean, s_clean)

