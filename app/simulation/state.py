"""驾驶模拟状态单例."""

from __future__ import annotations

from typing import Any

from pydantic import ValidationError

from app.schemas.context import DrivingContext

# ruff: noqa: ANN401
UpdateValue = Any


class _SimulationState:
    def __init__(self) -> None:
        self._context = DrivingContext()

    def get_context(self) -> DrivingContext:
        return self._context

    def update(self, field_path: str, value: UpdateValue) -> None:
        parts = field_path.split(".")
        if not parts:
            raise ValueError("field_path must not be empty")

        obj: Any = self._context
        for part in parts[:-1]:
            obj = getattr(obj, part)

        attr_name = parts[-1]
        current_model = type(obj)
        try:
            validated = current_model.model_validate(
                {**obj.model_dump(), attr_name: value}
            )
        except ValidationError:
            raise

        new_root = self._context.model_copy(deep=True)
        parent = new_root
        for part in parts[:-1]:
            parent = getattr(parent, part)
        setattr(parent, attr_name, getattr(validated, attr_name))
        self._context = new_root

    def set_preset(self, context_dict: dict[str, Any]) -> None:
        self._context = DrivingContext.model_validate(context_dict)

    def reset(self) -> None:
        self._context = DrivingContext()


simulation_state = _SimulationState()


def reset_state() -> None:
    """重置模拟状态到默认值."""
    simulation_state.reset()
