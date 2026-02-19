"""
Plugin registry for enablement types.

Usage:
    from app.enablements.registry import register, get_plugin_class, list_registered

    @register
    class MyEnablement(EnablementPlugin):
        TYPE_ID = "my_type"
        ...
"""

from typing import Type

from app.enablements.base import EnablementPlugin

_REGISTRY: dict[str, Type[EnablementPlugin]] = {}


def register(cls: Type[EnablementPlugin]) -> Type[EnablementPlugin]:
    """Class decorator to register an EnablementPlugin subclass."""
    if not cls.TYPE_ID:
        raise ValueError(f"EnablementPlugin subclass {cls.__name__} must define TYPE_ID")
    _REGISTRY[cls.TYPE_ID] = cls
    return cls


def get_plugin_class(type_id: str) -> Type[EnablementPlugin]:
    if type_id not in _REGISTRY:
        raise ValueError(
            f"Unknown enablement type: '{type_id}'. "
            f"Registered types: {list(_REGISTRY.keys())}"
        )
    return _REGISTRY[type_id]


def list_registered() -> list[dict]:
    """Return metadata for all registered plugins (used by GET /enablement-types)."""
    return [
        {
            "type_id": cls.TYPE_ID,
            "display_name": cls.DISPLAY_NAME,
            "description": cls.DESCRIPTION,
        }
        for cls in _REGISTRY.values()
    ]
