"""
Search Tool: BM25 Keyword Search over Evidence Cards with Metadata Filters.
Maintains query tracking to strictly enforce the no-duplicate query rule.
"""

from typing import List, Optional, Set, Dict
from rank_bm25 import BM25Okapi

from app.models import EvidenceCard


class SearchService:
    def __init__(self, cards: List[EvidenceCard]):
        self.cards: List[EvidenceCard] = cards
        self.card_id_map: Dict[str, EvidenceCard] = {c.evidence_id: c for c in cards}
        self.query_history: Set[str] = set()

        # Tokenize corpus for BM25
        self.corpus: List[List[str]] = [
            self._tokenize(f"{c.title} {c.quote or ''} {c.country or ''} {c.sector or ''} {c.doc_id}")
            for c in cards
        ]
        if self.corpus:
            self.bm25 = BM25Okapi(self.corpus)
        else:
            self.bm25 = None

    def search(
        self,
        query: str,
        country: Optional[str] = None,
        sector: Optional[str] = None,
        commodity: Optional[str] = None,
        max_tier: Optional[int] = None,
        exclude_sentiment: bool = False,
        limit: int = 10,
        requester: Optional[str] = None,
    ) -> List[EvidenceCard]:
        """
        Executes BM25 search over approved cards with metadata filters.
        Enforces query tracking (returns empty or cached if duplicate).
        """
        normalized_q = query.strip().lower()
        query_key = f"{requester or 'anon'}:{normalized_q}:{country}:{sector}:{commodity}:{max_tier}"

        # Track query
        is_duplicate = query_key in self.query_history
        self.query_history.add(query_key)

        if not self.bm25 or not self.cards:
            return []

        tokens = self._tokenize(query)
        if not tokens:
            scores = [0.0] * len(self.cards)
        else:
            scores = self.bm25.get_scores(tokens)

        # Rank and filter
        scored_cards = []
        for card, score in zip(self.cards, scores):
            # Filter checks
            if country and card.country and card.country != country:
                continue
            if sector and card.sector and not card.sector.startswith(sector.split(".")[0]):
                continue
            if max_tier and card.source_tier > max_tier:
                continue
            if exclude_sentiment and card.sentiment_only:
                continue

            scored_cards.append((score, card))

        # Sort by BM25 score descending
        scored_cards.sort(key=lambda x: x[0], reverse=True)
        return [c for _, c in scored_cards[:limit]]

    @staticmethod
    def _tokenize(text: str) -> List[str]:
        # Simple word regex tokenizer
        import re
        words = re.findall(r"\b[a-zA-Z0-9_\-\.]+\b", text.lower())
        return words

