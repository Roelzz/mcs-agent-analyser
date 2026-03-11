import asyncio

import reflex as rx

from web.state._base import _fetch_community_count

_CAT_MILESTONES: list[tuple[int, str, str]] = [
    (1000, "\U0001f406", "Legendary Leopard"),
    (500, "\U0001f42f", "Tiger Analyst"),
    (250, "\U0001f981", "Lion Mode"),
    (100, "\U0001f408\u200d\u2b1b", "Shadow Cat"),
    (50, "\U0001f408", "Prowling Cat"),
    (25, "\U0001f638", "Grinning Cat"),
    (10, "\U0001f63a", "Happy Cat"),
    (0, "\U0001f431", "Curious Kitten"),
]

_MILESTONE_THRESHOLDS: set[int] = {t for t, _, _ in _CAT_MILESTONES if t > 0}


class CounterMixin(rx.State, mixin=True):
    """Counter vars and handlers."""

    # Counter vars
    analyses_count: int = 0
    counter_animating: bool = False
    milestone_reached: bool = False

    @rx.var
    def cat_emoji(self) -> str:
        for threshold, emoji, _ in _CAT_MILESTONES:
            if self.analyses_count >= threshold:
                return emoji
        return "\U0001f431"

    @rx.var
    def cat_title(self) -> str:
        for threshold, _, title in _CAT_MILESTONES:
            if self.analyses_count >= threshold:
                return title
        return "Curious Kitten"

    async def _refresh_community_count(self):
        """Fetch community count from komarev and trigger animation if it changed."""
        prev = self.analyses_count
        self.analyses_count = await asyncio.to_thread(_fetch_community_count)
        if self.analyses_count > prev and prev > 0:
            self.counter_animating = True
            self.milestone_reached = any(prev < t <= self.analyses_count for t in _MILESTONE_THRESHOLDS)

    @rx.event
    def reset_counter_animation(self):
        self.counter_animating = False
        self.milestone_reached = False
