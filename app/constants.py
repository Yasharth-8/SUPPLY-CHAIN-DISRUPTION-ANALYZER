"""
System Constants, Thresholds, Conversion Factors, and Match Configs.
"""

from typing import Dict, Set, Pattern
import re
from app.vocabularies import Commodity, Metric

# Related commodities for pairing expansion
RELATED_COMMODITIES: Dict[Commodity, Set[Commodity]] = {
    Commodity.CRUDE_OIL: {Commodity.REFINED_FUELS},
    Commodity.REFINED_FUELS: {Commodity.CRUDE_OIL},
    Commodity.NATURAL_GAS: {Commodity.LNG},
    Commodity.LNG: {Commodity.NATURAL_GAS},
    Commodity.UREA: {Commodity.FERTILIZER, Commodity.DAP, Commodity.POTASH},
    Commodity.FERTILIZER: {Commodity.UREA, Commodity.DAP, Commodity.POTASH},
    Commodity.DAP: {Commodity.FERTILIZER, Commodity.UREA, Commodity.POTASH},
    Commodity.POTASH: {Commodity.FERTILIZER, Commodity.UREA, Commodity.DAP},
    Commodity.GRAIN: {Commodity.WHEAT, Commodity.SOYBEANS, Commodity.RICE},
    Commodity.RICE: {Commodity.GRAIN, Commodity.WHEAT},
    Commodity.WHEAT: {Commodity.GRAIN, Commodity.RICE},
    Commodity.SOYBEANS: {Commodity.GRAIN},
    Commodity.SEMICONDUCTORS: {Commodity.ELECTRONIC_COMPONENTS},
    Commodity.ELECTRONIC_COMPONENTS: {Commodity.SEMICONDUCTORS},
}

# Related parent sectors for input-output supply chain pairing
RELATED_SECTORS: Dict[str, Set[str]] = {
    "chemicals": {"agriculture", "energy"},
    "agriculture": {"chemicals"},
    "energy": {"logistics", "chemicals"},
    "logistics": {"energy"},
    "electronics": {"automotive"},
    "automotive": {"electronics"},
}

def are_commodities_related(c1: str, c2: str) -> bool:
    """Checks if two commodities are identical or closely related."""
    if c1 == c2:
        return True
    try:
        comm1 = Commodity(c1)
        comm2 = Commodity(c2)
        return comm2 in RELATED_COMMODITIES.get(comm1, set())
    except ValueError:
        return False

def are_sectors_related(s1: str, s2: str) -> bool:
    """Checks if two parent sectors are identical or adjacent in supply chain input/output."""
    if s1 == s2:
        return True
    return s2 in RELATED_SECTORS.get(s1, set())


# Materiality thresholds per metric
MATERIALITY_THRESHOLDS = {
    Metric.VOLUME_SHORTFALL: {"tonnes": 100_000.0, "bpd": 50_000.0},
    Metric.IMPORT_VOLUME_AT_RISK: {"tonnes": 100_000.0, "bpd": 50_000.0},
    Metric.PERMANENT_CAPACITY_LOSS: {"tonnes": 100_000.0, "bpd": 50_000.0},
    Metric.PRODUCTION_AT_RISK: 5.0,  # percent
    Metric.DELAY_DAYS: 3.0,          # days
    Metric.PRICE_INCREASE: 5.0,      # percent
}

# Operational limits
MAX_RUNS = 2
MAX_CLAIMS_PER_SIDE_PER_ROUND = 12
MAX_EVIDENCE_REQUESTS_PER_SIDE = 5
JUDGE_BATCH_SIZE = 5
ADVOCATE_MAX_QUERIES_PER_REQUEST = 3

# Unit conversion factors to metric tonnes
# 1 tonne crude oil ~ 7.33 barrels
BARRELS_PER_TONNE_CRUDE = 7.33

def bpd_to_tonnes_daily(bpd: float) -> float:
    return bpd / BARRELS_PER_TONNE_CRUDE

def tonnes_daily_to_bpd(tonnes: float) -> float:
    return tonnes * BARRELS_PER_TONNE_CRUDE

# Citation verification fuzzy match threshold (token overlap ratio)
CITATION_FUZZY_MATCH_THRESHOLD = 0.80

# Prompt injection regex patterns (case-insensitive)
PROMPT_INJECTION_PATTERNS = [
    re.compile(r"ignore\s+(all\s+)?(previous|prior|above)\s+instructions", re.IGNORECASE),
    re.compile(r"system\s*:\s*you\s+are", re.IGNORECASE),
    re.compile(r"you\s+are\s+now\s+a", re.IGNORECASE),
    re.compile(r"new\s+rule\s*:", re.IGNORECASE),
    re.compile(r"bypass\s+(the\s+)?guardrails", re.IGNORECASE),
    re.compile(r"disregard\s+(the\s+)?rules", re.IGNORECASE),
]

