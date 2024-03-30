from collections.abc import Callable
from typing import Any, Generic, Self, TypeVar, overload

FuncT = TypeVar("FuncT", bound=Callable[..., Any])
T1 = TypeVar("T1")
T2 = TypeVar("T2")


class Signal(Generic[FuncT]):
    """Thing."""

    @overload
    def __init__(self: Self[Callable[[], Any]]) -> None: ...
    @overload
    def __init__(
        self: Self[Callable[[], Any] | Callable[[T1], Any]], t1: type[T1]
    ) -> None: ...
    @overload
    def __init__(
        self: Self[Callable[[], Any] | Callable[[T1], Any] | Callable[[T1, T2], Any]],
        t1: type[T1],
        t2: type[T2],
    ) -> None: ...

    def connect(self, func: FuncT): ...
