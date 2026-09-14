"""Euro area membership, used to expand joint issues and to seed the country table."""

from dataclasses import dataclass


@dataclass(frozen=True)
class EuroCountry:
    code: str
    name: str
    eurozone_since: int
    is_micro_state: bool = False


EURO_COUNTRIES: tuple[EuroCountry, ...] = (
    EuroCountry("AD", "Andorra", 2014, True),
    EuroCountry("AT", "Austria", 1999),
    EuroCountry("BE", "Belgium", 1999),
    EuroCountry("BG", "Bulgaria", 2026),
    EuroCountry("CY", "Cyprus", 2008),
    EuroCountry("DE", "Germany", 1999),
    EuroCountry("EE", "Estonia", 2011),
    EuroCountry("ES", "Spain", 1999),
    EuroCountry("FI", "Finland", 1999),
    EuroCountry("FR", "France", 1999),
    EuroCountry("GR", "Greece", 2001),
    EuroCountry("HR", "Croatia", 2023),
    EuroCountry("IE", "Ireland", 1999),
    EuroCountry("IT", "Italy", 1999),
    EuroCountry("LT", "Lithuania", 2015),
    EuroCountry("LU", "Luxembourg", 1999),
    EuroCountry("LV", "Latvia", 2014),
    EuroCountry("MC", "Monaco", 2002, True),
    EuroCountry("MT", "Malta", 2008),
    EuroCountry("NL", "Netherlands", 1999),
    EuroCountry("PT", "Portugal", 1999),
    EuroCountry("SI", "Slovenia", 2007),
    EuroCountry("SK", "Slovakia", 2009),
    EuroCountry("SM", "San Marino", 2002, True),
    EuroCountry("VA", "Vatican City", 2002, True),
)


def member_states(year: int, include_micro_states: bool = False) -> list[EuroCountry]:
    return [
        c
        for c in EURO_COUNTRIES
        if c.eurozone_since <= year and (include_micro_states or not c.is_micro_state)
    ]
