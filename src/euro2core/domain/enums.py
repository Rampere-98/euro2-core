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
