from __future__ import annotations

from app.services.place_resolver import resolve_place_mentions


def test_place_resolver_returns_coex_station_candidates() -> None:
    mentions = resolve_place_mentions("휠체어로 코엑스 갈 수 있어?")

    assert len(mentions) == 1
    mention = mentions[0].mention
    assert mention.place_name == "코엑스"
    assert [candidate.label for candidate in mention.candidates] == [
        "2호선 삼성역",
        "9호선 봉은사역",
    ]


def test_place_resolver_returns_single_hongdae_candidate() -> None:
    mentions = resolve_place_mentions("홍대에서 출발할래")

    assert len(mentions) == 1
    mention = mentions[0].mention
    assert mention.place_name == "홍대"
    assert len(mention.candidates) == 1
    assert mention.candidates[0].label == "2호선 홍대입구역"


def test_place_resolver_returns_ktx_seoul_station_candidates() -> None:
    mentions = resolve_place_mentions("서울역 KTX에서 잠실까지 유모차로 갈만해?")

    assert len(mentions) == 1
    mention = mentions[0].mention
    assert mention.place_name == "서울역 KTX"
    assert [candidate.label for candidate in mention.candidates] == [
        "1호선 서울역",
        "4호선 서울역",
    ]


def test_place_resolver_returns_ddp_station_candidates() -> None:
    mentions = resolve_place_mentions("DDP까지 휠체어로 갈 수 있어?")

    assert len(mentions) == 1
    mention = mentions[0].mention
    assert mention.place_name == "DDP"
    assert [candidate.label for candidate in mention.candidates] == [
        "2호선 동대문역사문화공원역",
        "4호선 동대문역사문화공원역",
        "5호선 동대문역사문화공원역",
    ]
