import httpx
import pytest
import respx
from sqlalchemy import select

from euro2core.catalog.ingest_ecb import ECB_IMAGE_AUTHOR
from euro2core.catalog.ingest_national import ingest_national_sides
from euro2core.catalog.seed import ensure_reference_data
from euro2core.domain.enums import CoinKind, VerificationStatus
from euro2core.domain.models import CoinImage, CoinType
from euro2core.images.fetcher import ImageFetcher
from euro2core.sources.ecb.national import NationalSideImage

pytestmark = pytest.mark.integration

PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 32
BASE = "https://www.ecb.europa.eu/euro/coins/common/shared/img/be/"


def _circulation(country: str, year: int, numista_id: int) -> CoinType:
    return CoinType(
        kind=CoinKind.CIRCULATION,
        country_code=country,
        year=year,
        numista_type_id=numista_id,
        verification_status=VerificationStatus.DOCUMENTED,
    )


@respx.mock
async def test_circulation_types_get_the_design_of_their_year(session, tmp_path):
    respx.get(url__startswith=BASE).mock(
        return_value=httpx.Response(200, content=PNG, headers={"Content-Type": "image/jpeg"})
    )
    await ensure_reference_data(session)
    albert_1999 = _circulation("BE", 1999, 80)
    albert_2008 = _circulation("BE", 2008, 6293)
    philippe = _circulation("BE", 2014, 56039)
    commemorative = CoinType(
        kind=CoinKind.COMMEMORATIVE,
        country_code="BE",
        year=2014,
        ecb_ref="2014/BE/x",
        verification_status=VerificationStatus.DOCUMENTED,
    )
    session.add_all([albert_1999, albert_2008, philippe, commemorative])
    await session.commit()
    images = [
        NationalSideImage(BASE + "Belgium_2euroAl.jpg", None),
        NationalSideImage(BASE + "Belgium_2euro_2008.jpg", 2008),
        NationalSideImage(BASE + "Belgium_2euro_2014ph.jpg", 2014),
    ]
    fetcher = ImageFetcher(root=tmp_path / "img", user_agent="test")

    stored = await ingest_national_sides(session, "BE", images, fetcher)
    await session.commit()

    assert stored == 3
    rows = {
        r.type_id: r
        for r in (
            await session.scalars(select(CoinImage).where(CoinImage.author == ECB_IMAGE_AUTHOR))
        ).all()
    }
    assert rows[albert_1999.id].source_url.endswith("Belgium_2euroAl.jpg")
    assert rows[albert_2008.id].source_url.endswith("Belgium_2euro_2008.jpg")
    assert rows[philippe.id].source_url.endswith("Belgium_2euro_2014ph.jpg")
    assert commemorative.id not in rows  # commemoratives keep their own ECB photo
    assert all(r.local_path and r.sha256 for r in rows.values())

    # idempotent
    assert await ingest_national_sides(session, "BE", images, fetcher) == 0
