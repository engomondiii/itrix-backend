"""
Room router.

Maps a visitor type / persona to the most relevant visitor room on the public site,
and vice-versa. Used to personalise routing and (later) to suggest the right room.
Room + visitor-type values match ``apps.visitors.models`` and
``itrix-web/src/types/room.types.ts``.
"""

from __future__ import annotations

# visitor_type -> canonical room slug
_VISITOR_TYPE_TO_ROOM = {
    "problem_owner": "bottleneck",
    "technical": "technical",
    "research": "research",
    "investor": "investor",
    "partner": "partner",
    "shareholder": "shareholder",
    "media": "media",
    "creator": "creator",
    "public_infrastructure": "public-infrastructure",
    "explorer": "explore",
}

# room slug -> visitor_type
_ROOM_TO_VISITOR_TYPE = {room: vt for vt, room in _VISITOR_TYPE_TO_ROOM.items()}


class RoomRouter:
    @staticmethod
    def room_for_visitor_type(visitor_type: str | None) -> str:
        return _VISITOR_TYPE_TO_ROOM.get(visitor_type or "", "explore")

    @staticmethod
    def visitor_type_for_room(room: str | None) -> str:
        return _ROOM_TO_VISITOR_TYPE.get(room or "", "unknown")


def room_for_visitor_type(visitor_type: str | None) -> str:
    return RoomRouter.room_for_visitor_type(visitor_type)
