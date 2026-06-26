from __future__ import annotations

from app.schemas.accessibility import MobilityProfile


def requires_elevator(profile: MobilityProfile) -> bool:
    return (
        profile.need_elevator_only
        or profile.wheelchair
        or not profile.can_use_stairs
        or (not profile.can_use_escalator and not profile.can_use_stairs)
    )

