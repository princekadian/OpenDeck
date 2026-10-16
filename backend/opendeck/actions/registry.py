from __future__ import annotations

from .base import Action

# Menu order and labels. Actions declare their category id; the editor groups by this list.
CATEGORIES: list[tuple[str, str]] = [
    ("open", "Open"),
    ("system", "System"),
    ("audio", "Audio"),
    ("media", "Media"),
    ("soundboard", "Sound effects"),
    ("keyboard", "Keyboard"),
    ("display", "Display"),
    ("window", "Window"),
    ("applications", "Applications"),
    ("navigation", "Navigation"),
    ("workflow", "Workflow"),
    ("streaming", "Streaming"),
    ("advanced", "Advanced"),
]
_CATEGORY_IDS = {cid for cid, _ in CATEGORIES}


class ActionRegistry:
    def __init__(self) -> None:
        self._actions: dict[str, Action] = {}

    def register(self, action: Action) -> None:
        if action.type in self._actions:
            raise ValueError(f"Action type already registered: {action.type}")
        if action.category not in _CATEGORY_IDS:
            raise ValueError(f"Unknown category '{action.category}' for {action.type}")
        self._actions[action.type] = action
        action.bind(self)

    def get(self, action_type: str) -> Action | None:
        return self._actions.get(action_type)

    def all(self) -> list[Action]:
        """Registration order within each category, categories in menu order."""
        order = {cid: i for i, (cid, _) in enumerate(CATEGORIES)}
        return sorted(self._actions.values(), key=lambda a: order[a.category])

    def catalog(self) -> dict:
        return {
            "categories": [{"id": cid, "label": label} for cid, label in CATEGORIES],
            "actions": [a.describe() for a in self.all()],
        }


def build_default_registry() -> ActionRegistry:
    from .builtin import all_builtin_actions

    registry = ActionRegistry()
    for action in all_builtin_actions():
        registry.register(action)
    return registry
