import uuid

import pytest
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from euro2core.domain.enums import CoinKind, Finish, Packaging
from euro2core.domain.models import CoinIssue, CoinType, Country

pytestmark = pytest.mark.integration


async def _germany(session) -> None:
    session.add(Country(code="DE", name_en="Germany", eurozone_since=1999))
    await session.flush()


async def test_type_with_five_mint_issues_round_trips(session):
    await _germany(session)
    ct = CoinType(kind=CoinKind.COMMEMORATIVE, country_code="DE", year=2006, ecb_ref="2006/DE/sh")
    session.add(ct)
    await session.flush()
    for mark in "ADFGJ":
        session.add(CoinIssue(type_id=ct.id, year=2006, mint_mark=mark, finish=Finish.CIRCULATION))
    await session.commit()

    issues = (await session.scalars(select(CoinIssue).where(CoinIssue.type_id == ct.id))).all()
    assert sorted(i.mint_mark for i in issues) == list("ADFGJ")
    assert all(i.packaging == Packaging.LOOSE for i in issues)


async def test_same_variant_twice_is_rejected_by_the_database(session):
    await _germany(session)
    ct = CoinType(kind=CoinKind.CIRCULATION, country_code="DE", year=2008)
    session.add(ct)
    await session.flush()
    session.add(
        CoinIssue(type_id=ct.id, year=2008, mint_mark="", finish=Finish.BU, packaging=Packaging.SET)
    )
    await session.flush()
    session.add(
        CoinIssue(type_id=ct.id, year=2008, mint_mark="", finish=Finish.BU, packaging=Packaging.SET)
    )
    with pytest.raises(IntegrityError):
        await session.flush()


async def test_error_type_must_reference_its_base_type(session):
    await _germany(session)
    session.add(CoinType(kind=CoinKind.ERROR, country_code="DE", year=2008))
    with pytest.raises(IntegrityError):
        await session.flush()


async def test_normal_type_must_not_reference_a_base_type(session):
    await _germany(session)
    base = CoinType(kind=CoinKind.COMMEMORATIVE, country_code="DE", year=2008)
    session.add(base)
    await session.flush()
    session.add(
        CoinType(kind=CoinKind.COMMEMORATIVE, country_code="DE", year=2008, base_type_id=base.id)
    )
    with pytest.raises(IntegrityError):
        await session.flush()


async def test_unknown_country_is_rejected(session):
    session.add(CoinType(kind=CoinKind.COMMEMORATIVE, country_code="XX", year=2008))
    with pytest.raises(IntegrityError):
        await session.flush()


async def test_uuid_primary_keys_are_generated_client_side(session):
    await _germany(session)
    ct = CoinType(kind=CoinKind.COMMEMORATIVE, country_code="DE", year=2006)
    assert ct.id is None
    session.add(ct)
    await session.flush()
    assert isinstance(ct.id, uuid.UUID)
