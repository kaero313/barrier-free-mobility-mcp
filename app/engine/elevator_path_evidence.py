from __future__ import annotations

from dataclasses import dataclass

from app.schemas.accessibility import AccessibilityEvidenceStatus
from app.schemas.facility import AccessibleFacility, FacilityType


@dataclass(frozen=True)
class ElevatorPathEvidence:
    platform_to_concourse: AccessibilityEvidenceStatus
    transfer_path: AccessibilityEvidenceStatus
    exit_path: AccessibilityEvidenceStatus


def evaluate_elevator_path_evidence(
    *,
    required: bool,
    role: str,
    station_has_elevator: AccessibilityEvidenceStatus,
    facilities: list[AccessibleFacility],
) -> ElevatorPathEvidence:
    if not required:
        return ElevatorPathEvidence(
            platform_to_concourse=AccessibilityEvidenceStatus.NOT_APPLICABLE,
            transfer_path=AccessibilityEvidenceStatus.NOT_APPLICABLE,
            exit_path=AccessibilityEvidenceStatus.NOT_APPLICABLE,
        )

    if station_has_elevator == AccessibilityEvidenceStatus.FAILED:
        return ElevatorPathEvidence(
            platform_to_concourse=AccessibilityEvidenceStatus.FAILED,
            transfer_path=(
                AccessibilityEvidenceStatus.FAILED
                if role == "transfer"
                else AccessibilityEvidenceStatus.NOT_APPLICABLE
            ),
            exit_path=(
                AccessibilityEvidenceStatus.FAILED
                if role in {"origin", "destination"}
                else AccessibilityEvidenceStatus.NOT_APPLICABLE
            ),
        )

    elevator_texts = [
        _facility_evidence_text(facility)
        for facility in facilities
        if facility.facility_type == FacilityType.ELEVATOR
    ]
    platform_to_concourse = (
        AccessibilityEvidenceStatus.CONFIRMED
        if any(_mentions_platform_to_concourse(text) for text in elevator_texts)
        else AccessibilityEvidenceStatus.UNVERIFIED
    )
    transfer_path = AccessibilityEvidenceStatus.NOT_APPLICABLE
    if role == "transfer":
        transfer_path = (
            AccessibilityEvidenceStatus.CONFIRMED
            if any(_mentions_transfer_path(text) for text in elevator_texts)
            else AccessibilityEvidenceStatus.UNVERIFIED
        )
    exit_path = AccessibilityEvidenceStatus.NOT_APPLICABLE
    if role in {"origin", "destination"}:
        exit_path = (
            AccessibilityEvidenceStatus.CONFIRMED
            if any(_mentions_exit_path(text) for text in elevator_texts)
            else AccessibilityEvidenceStatus.UNVERIFIED
        )

    return ElevatorPathEvidence(
        platform_to_concourse=platform_to_concourse,
        transfer_path=transfer_path,
        exit_path=exit_path,
    )


def _facility_evidence_text(facility: AccessibleFacility) -> str:
    return " ".join(
        str(value).strip().lower()
        for value in (
            facility.facility_name,
            facility.location_description,
            facility.operation_section,
        )
        if value
    )


def _mentions_platform_to_concourse(value: str) -> bool:
    return (
        ("승강장" in value and "대합실" in value)
        or ("platform" in value and "concourse" in value)
    )


def _mentions_transfer_path(value: str) -> bool:
    return "환승" in value or "transfer" in value


def _mentions_exit_path(value: str) -> bool:
    return any(marker in value for marker in ("출구", "출입구", "외부", "street exit"))
