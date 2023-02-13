"""pyi file required until mypyc supports ParamSpec."""

import weakref
from typing import Any, Callable, Generic, ParamSpec, TypeVar

T = TypeVar("T")
R = TypeVar("R")
P = ParamSpec("P")

class WeakCallback(Generic[P, R]):
    """Weak reference to a callable."""

    _obj_ref: weakref.ReferenceType[Any]
    _max_args: int | None = None

    def callback(self, args: tuple[Any, ...]) -> bool:
        """Call the referenced function. Return True if weakref is dead.

        This implementation should be as fast as possible.
        """
    def __call__(self, *args: P.args, **kwargs: P.kwargs) -> R:
        """Call the referenced function.  Raise a RuntimeError if it is dead."""
    def __eq__(self, other: object) -> bool:
        """Return True if `other` is equal to this WeakCallback."""
    def slot(self) -> Callable[P, R]:
        """Reconstruct the original slot, or raise a RuntimeError."""
    def is_alive(self) -> bool:
        """Return True if the slot is still alive."""
    @classmethod
    def create(
        cls, func: Callable[P, R], max_args: int | None = None, key: str | None = None
    ) -> WeakCallback[P, R]: ...

class _SetitemCaller(WeakCallback): ...
class _SetattrCaller(WeakCallback): ...
