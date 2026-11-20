"""
Controlled Vocabularies for Supply Chain Disruption Analyser.
Strictly defines fixed enums, hierarchy resolvers, and related-values mappings.
"""

from enum import Enum
from typing import Optional, Set, Any, List


class Country(str, Enum):
    RU = "RU"
    IR = "IR"
    AE = "AE"
    TR = "TR"
    BR = "BR"
    CN = "CN"
    IN = "IN"
    US = "US"
    NL = "NL"
    DE = "DE"
    EU = "EU"
    SA = "SA"
    SG = "SG"
    GB = "GB"
    JP = "JP"
    KR = "KR"
    AU = "AU"
    EG = "EG"
    YE = "YE"
    UA = "UA"
    RO = "RO"
    BG = "BG"
    PL = "PL"
    NG = "NG"
    AO = "AO"
    CA = "CA"
    QA = "QA"
    KW = "KW"
    IQ = "IQ"
    OM = "OM"
    KZ = "KZ"
    AT = "AT"
    CH = "CH"
    MY = "MY"
    ID = "ID"
    TH = "TH"
    PH = "PH"
    ZA = "ZA"
    MZ = "MZ"
    TW = "TW"
    GLOBAL = "GLOBAL"


class Sector(str, Enum):
    # Energy
    ENERGY_UPSTREAM = "energy.upstream"
    ENERGY_REFINING = "energy.refining"
    # Logistics
    LOGISTICS_SHIPPING = "logistics.shipping"
    LOGISTICS_PORTS = "logistics.ports"
    # Agriculture
    AGRICULTURE_FARMING = "agriculture.farming"
    AGRICULTURE_PROCESSING = "agriculture.processing"
    # Chemicals
    CHEMICALS_FERTILIZER = "chemicals.fertilizer"
    CHEMICALS_PETROCHEMICALS = "chemicals.petrochemicals"
    # Standalone sectors
    MINING = "mining"
    AUTOMOTIVE = "automotive"
    ELECTRONICS = "electronics"
    PHARMACEUTICALS = "pharmaceuticals"

    @classmethod
    def get_parent(cls, sector_val: Any) -> str:
        """Returns the parent sector for pairing (e.g. 'energy.upstream' -> 'energy')."""
        if hasattr(sector_val, "value"):
            val = str(sector_val.value)
        else:
            val = str(sector_val)
        if val.startswith("Sector."):
            val = val[7:]
        if "." in val:
            return val.split(".")[0].lower()
        return val.lower()


class Commodity(str, Enum):
    CRUDE_OIL = "crude_oil"
    REFINED_FUELS = "refined_fuels"
    NATURAL_GAS = "natural_gas"
    LNG = "lng"
    COAL = "coal"
    UREA = "urea"
    POTASH = "potash"
    DAP = "dap"
    FERTILIZER = "fertilizer"
    GRAIN = "grain"
    RICE = "rice"
    IRON_ORE = "iron_ore"
    SOYBEANS = "soybeans"
    WHEAT = "wheat"
    SUGAR = "sugar"
    SEMICONDUCTORS = "semiconductors"
    ELECTRONIC_COMPONENTS = "electronic_components"
    GRAPHITE = "graphite"
    POLYMERS = "polymers"


class Mechanism(str, Enum):
    CHOKEPOINT_DISRUPTION = "chokepoint_disruption"
    EXPORT_BAN = "export_ban"
    PORT_STRIKE = "port_strike"
    ROUTE_REROUTING = "route_rerouting"
    SANCTIONS = "sanctions"
    MILITARY_CONFLICT = "military_conflict"
    WEATHER_DISRUPTION = "weather_disruption"
    INFRASTRUCTURE_FAILURE = "infrastructure_failure"
    REGULATORY_CHANGE = "regulatory_change"
    DEMAND_SHOCK = "demand_shock"
    SUPPLY_CONCENTRATION = "supply_concentration"
    INSURANCE_WITHDRAWAL = "insurance_withdrawal"


class Metric(str, Enum):
    DELAY_DAYS = "delay_days"
    VOLUME_SHORTFALL = "volume_shortfall"
    PERMANENT_CAPACITY_LOSS = "permanent_capacity_loss"
    PRODUCTION_AT_RISK = "production_at_risk"
    IMPORT_VOLUME_AT_RISK = "import_volume_at_risk"
    PRICE_INCREASE = "price_increase"


class TimeHorizon(str, Enum):
    T_0_7D = "0-7d"
    T_8_21D = "8-21d"
    T_22_60D = "22-60d"
    T_61_90D = "61-90d"
    T_90_PLUS = "90+d"


class EventStatus(str, Enum):
    CONFIRMED = "confirmed"
    REPORTED = "reported"
    CONTRADICTED = "contradicted"
    UNSUPPORTED = "unsupported"
    HYPOTHETICAL = "hypothetical"


class ClaimType(str, Enum):
    SOURCED_FACT = "sourced_fact"
    INFERENCE = "inference"


class ClaimStatus(str, Enum):
    ORIGINAL = "original"
    REBUTTAL = "rebuttal"
    REVISED = "revised"
    WITHDRAWN = "withdrawn"
    CONCEDED = "conceded"


class ResponseType(str, Enum):
    REBUT = "rebut"
    NARROW = "narrow"
    CONTEXTUALIZE = "contextualize"
    CONCEDE = "concede"


class RulingVerdict(str, Enum):
    SUSTAINED = "sustained"
    PARTIALLY_SUSTAINED = "partially_sustained"
    OVERRULED = "overruled"
    INSUFFICIENT_EVIDENCE = "insufficient_evidence"


class FindingClassification(str, Enum):
    ESTABLISHED = "established"
    CONTESTED = "contested"
    CONCEDED = "conceded"
    UNOPPOSED = "unopposed"
    INSUFFICIENT = "insufficient"


class ConfidenceLevel(str, Enum):
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"

