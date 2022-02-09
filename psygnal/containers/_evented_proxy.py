from functools import partial
from typing import Any, Dict, Generic, List, TypeVar
from weakref import finalize

from wrapt import ObjectProxy

from .._group import SignalGroup
from .._signal import Signal

T = TypeVar("T")
_UNSET = object()


class Events(SignalGroup):
    """ObjectProxy events."""

    attribute_set = Signal(str, object)
    attribute_deleted = Signal(str)
    item_set = Signal(object, object)
    item_deleted = Signal(object)
    in_place = Signal(str, object)


class CallableEvents(Events):
    """CallableObjectProxy events."""

    called = Signal(tuple, dict)


# we're using a cache instead of setting the events object directly on the proxy
# because when wrapt is compiled as a C extensions, the ObjectProxy is not allowed
# to add any new attributes.
_OBJ_CACHE: Dict[int, Events] = {}


class _EventedObjectProxy(ObjectProxy, Generic[T]):  # type: ignore
    @property
    def events(self) -> Events:
        obj_id = id(self)
        if obj_id not in _OBJ_CACHE:
            _OBJ_CACHE[obj_id] = Events()
            finalize(self, partial(_OBJ_CACHE.pop, obj_id, None))
        return _OBJ_CACHE[obj_id]

    def __setattr__(self, name: str, value: None) -> None:
        before = getattr(self, name, _UNSET)
        super().__setattr__(name, value)
        after = getattr(self, name, _UNSET)
        if before is not after:
            self.events.attribute_set(name, after)

    def __delattr__(self, name: str) -> None:
        super().__delattr__(name)
        self.events.attribute_deleted(name)

    def __setitem__(self, key: Any, value: Any) -> None:
        before = self[key]
        super().__setitem__(key, value)
        after = self[key]
        if before is not after:
            self.events.item_set(key, after)

    def __delitem__(self, key: Any) -> None:
        super().__delitem__(key)
        self.events.item_deleted(key)

    def __repr__(self) -> str:
        return repr(self.__wrapped__)

    def __dir__(self) -> List[str]:
        return dir(self.__wrapped__) + ["events"]

    def __iadd__(self, other: Any) -> T:
        self.events.in_place("add", other)
        return super().__iadd__(other)  # type: ignore

    def __isub__(self, other: Any) -> T:
        self.events.in_place("sub", other)
        return super().__isub__(other)  # type: ignore

    def __imul__(self, other: Any) -> T:
        self.events.in_place("mul", other)
        return super().__imul__(other)  # type: ignore

    def __imatmul__(self, other: Any) -> T:
        self.events.in_place("matmul", other)
        self.__wrapped__ @= other  # not in wrapt  # type: ignore
        return self

    def __itruediv__(self, other: Any) -> T:
        self.events.in_place("truediv", other)
        return super().__itruediv__(other)  # type: ignore

    def __ifloordiv__(self, other: Any) -> T:
        self.events.in_place("floordiv", other)
        return super().__ifloordiv__(other)  # type: ignore

    def __imod__(self, other: Any) -> T:
        self.events.in_place("mod", other)
        return super().__imod__(other)  # type: ignore

    def __ipow__(self, other: Any) -> T:
        self.events.in_place("pow", other)
        return super().__ipow__(other)  # type: ignore

    def __ilshift__(self, other: Any) -> T:
        self.events.in_place("lshift", other)
        return super().__ilshift__(other)  # type: ignore

    def __irshift__(self, other: Any) -> T:
        self.events.in_place("rshift", other)
        return super().__irshift__(other)  # type: ignore

    def __iand__(self, other: Any) -> T:
        self.events.in_place("and", other)
        return super().__iand__(other)  # type: ignore

    def __ixor__(self, other: Any) -> T:
        self.events.in_place("xor", other)
        return super().__ixor__(other)  # type: ignore

    def __ior__(self, other: Any) -> T:
        self.events.in_place("or", other)
        return super().__ior__(other)  # type: ignore


class _EventedCallableObjectProxy(_EventedObjectProxy):
    @property
    def events(self) -> CallableEvents:
        obj_id = id(self)
        if obj_id not in _OBJ_CACHE:
            _OBJ_CACHE[obj_id] = CallableEvents()
            finalize(self, partial(_OBJ_CACHE.pop, obj_id, None))
        return _OBJ_CACHE[obj_id]  # type: ignore

    def __call__(self, *args: Any, **kwargs: Any) -> Any:
        self.events.called(args, kwargs)
        return self.__wrapped__(*args, **kwargs)


def EventedObjectProxy(target: T) -> T:
    """Create a proxy of `target` that includes an `events` SignalGroup.

    The events available at target.events include:
        attribute_set = Signal(str, object)
        attribute_deleted = Signal(str)
        item_set = Signal(object, object)
        item_deleted = Signal(object)
        in_place = Signal(str, object)

    and if `target` is callable:
        called = Signal(tuple, dict)
    """
    if callable(target):
        return _EventedCallableObjectProxy(target)
    else:
        return _EventedObjectProxy(target)
