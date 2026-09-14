from enum import StrEnum


class CoinKind(StrEnum):
    COMMEMORATIVE = "commemorative"
    CIRCULATION = "circulation"
    ERROR = "error"


class VerificationStatus(StrEnum):
    DOCUMENTED = "documented"
    PENDING_EXPERT = "pending_expert"


class Finish(StrEnum):
    CIRCULATION = "circulation"
    BU = "bu"
    PROOF = "proof"


class Packaging(StrEnum):
    LOOSE = "loose"
    COINCARD = "coincard"
    SET = "set"


class Grade(StrEnum):
    CIRCULATED = "circulated"
    UNC = "unc"
    BU = "bu"
    PROOF = "proof"
    UNKNOWN = "unknown"


class ObservationKind(StrEnum):
    SOLD = "sold"
    ASKING = "asking"
    AUCTION_OPEN = "auction_open"  # live auction; current bid is neither a sale nor an ask
    AUCTION_CLOSED = "auction_closed"


class SourceKind(StrEnum):
    CATALOG = "catalog"
    MARKET = "market"


class ImageSide(StrEnum):
    OBVERSE = "obverse"
    REVERSE = "reverse"
    EDGE = "edge"


class SyncStatus(StrEnum):
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"


class Plan(StrEnum):
    FREE = "free"
    PRO = "pro"


class Role(StrEnum):
    USER = "user"
    EXPERT = "expert"
    ADMIN = "admin"


class ListingStatus(StrEnum):
    ACTIVE = "active"
    SOLD = "sold"
    WITHDRAWN = "withdrawn"


class OfferStatus(StrEnum):
    PENDING = "pending"
    ACCEPTED = "accepted"
    REJECTED = "rejected"
    WITHDRAWN = "withdrawn"


class ReportStatus(StrEnum):
    PENDING = "pending"
    VALIDATED = "validated"
    REJECTED = "rejected"
