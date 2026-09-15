from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from euro2core.domain.enums import SourceKind
from euro2core.domain.models import Country, Source

# (code, name, eurozone_since, is_micro_state)
COUNTRIES: tuple[tuple[str, str, int | None, bool], ...] = (
    ("AD", "Andorra", 2014, True),
    ("AT", "Austria", 1999, False),
    ("BE", "Belgium", 1999, False),
    ("BG", "Bulgaria", 2026, False),
    ("CY", "Cyprus", 2008, False),
    ("DE", "Germany", 1999, False),
    ("EE", "Estonia", 2011, False),
    ("ES", "Spain", 1999, False),
    ("FI", "Finland", 1999, False),
    ("FR", "France", 1999, False),
    ("GR", "Greece", 2001, False),
    ("HR", "Croatia", 2023, False),
    ("IE", "Ireland", 1999, False),
    ("IT", "Italy", 1999, False),
    ("LT", "Lithuania", 2015, False),
    ("LU", "Luxembourg", 1999, False),
    ("LV", "Latvia", 2014, False),
    ("MC", "Monaco", 2002, True),
    ("MT", "Malta", 2008, False),
    ("NL", "Netherlands", 1999, False),
    ("PT", "Portugal", 1999, False),
    ("SI", "Slovenia", 2007, False),
    ("SK", "Slovakia", 2009, False),
    ("SM", "San Marino", 2002, True),
    ("VA", "Vatican City", 2002, True),
)

# (code, name, authority_rank, kind, base_url)
SOURCES: tuple[tuple[str, str, int, SourceKind, str], ...] = (
    (
        "ecb",
        "European Central Bank",
        100,
        SourceKind.CATALOG,
        "https://www.ecb.europa.eu/euro/coins/",
    ),
    ("numista", "Numista", 50, SourceKind.CATALOG, "https://en.numista.com/"),
    ("ebay", "eBay", 10, SourceKind.MARKET, "https://www.ebay.com/"),
    ("euro2", "Euro2 collectors", 30, SourceKind.MARKET, "euro2://"),
)


async def ensure_reference_data(session: AsyncSession) -> None:
    existing_countries = set((await session.scalars(select(Country.code))).all())
    for code, name, since, micro in COUNTRIES:
        if code not in existing_countries:
            session.add(
                Country(code=code, name_en=name, eurozone_since=since, is_micro_state=micro)
            )
    existing_sources = set((await session.scalars(select(Source.code))).all())
    for code, name, rank, kind, url in SOURCES:
        if code not in existing_sources:
            session.add(Source(code=code, name=name, authority_rank=rank, kind=kind, base_url=url))
    await session.flush()


async def get_source(session: AsyncSession, code: str) -> Source:
    return (await session.scalars(select(Source).where(Source.code == code))).one()
