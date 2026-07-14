from __future__ import annotations

import pytest

from app.schemas.accessibility import AccessibilityEvidenceStatus
from app.schemas.facility import AccessibleFacility, FacilityStatus, FacilityType
from app.services.accessibility_checks import line_match_evidence
from app.services.station_context import StationLookupContext


@pytest.mark.parametrize("facility_line", ["2", "02", "2호선", "Line 2"])
def test_line_match_evidence_normalizes_equivalent_line_formats(
    facility_line: str,
) -> None:
    context = StationLookupContext(station_name="홍대입구", line="2")
    elevator = AccessibleFacility(
        station_name="홍대입구",
        line=facility_line,
        facility_type=FacilityType.ELEVATOR,
        status=FacilityStatus.AVAILABLE,
    )

    evidence = line_match_evidence(
        context,
        [elevator],
        AccessibilityEvidenceStatus.CONFIRMED,
    )

    assert evidence == AccessibilityEvidenceStatus.CONFIRMED


def test_line_match_evidence_keeps_missing_source_line_unverified() -> None:
    context = StationLookupContext(station_name="홍대입구", line="2")
    elevator = AccessibleFacility(
        station_name="홍대입구",
        line=None,
        facility_type=FacilityType.ELEVATOR,
        status=FacilityStatus.AVAILABLE,
    )

    evidence = line_match_evidence(
        context,
        [elevator],
        AccessibilityEvidenceStatus.CONFIRMED,
    )

    assert evidence == AccessibilityEvidenceStatus.UNVERIFIED


def test_line_match_evidence_marks_real_mismatch_failed() -> None:
    context = StationLookupContext(station_name="고속터미널", line="9")
    elevator = AccessibleFacility(
        station_name="고속터미널",
        line="7호선",
        facility_type=FacilityType.ELEVATOR,
        status=FacilityStatus.AVAILABLE,
    )

    evidence = line_match_evidence(
        context,
        [elevator],
        AccessibilityEvidenceStatus.CONFIRMED,
    )

    assert evidence == AccessibilityEvidenceStatus.FAILED
