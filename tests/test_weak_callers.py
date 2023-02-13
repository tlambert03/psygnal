import weakref
from functools import partial
from typing import Any

import pytest

from psygnal import WeakCallback

VAL = 42


def _make_ref_and_caller(
    obj: Any, target: Any = None, key: Any = None, returns: Any = VAL
) -> tuple[weakref.ReferenceType, WeakCallback]:
    ref = weakref.ref(obj)
    caller: "WeakCallback[[int], Any]" = WeakCallback.create(target or obj, key=key)
    assert caller(VAL) == returns
    return ref, caller


def _assert_dead(ref: weakref.ref, caller: "WeakCallback[[int], Any]") -> None:
    assert not ref()
    assert not caller.is_alive()
    assert caller.callback(VAL) is True
    with pytest.raises(RuntimeError):
        caller(VAL)


def test_weak_function_caller() -> None:
    def func(x: int) -> int:
        return x

    ref, caller = _make_ref_and_caller(func)
    del func
    _assert_dead(ref, caller)


def test_weak_method_caller() -> None:
    class Foo:
        def func(self, x: int) -> int:
            return x

    foo = Foo()
    ref, caller = _make_ref_and_caller(foo, foo.func)
    del foo
    _assert_dead(ref, caller)


def test_weak_partial_method_caller() -> None:
    class Foo:
        def func(self, y: int, x: int) -> int:
            return x

    foo = Foo()
    ref, caller = _make_ref_and_caller(foo, partial(foo.func, 2345))
    del foo
    _assert_dead(ref, caller)


def test_weak_setattr_caller() -> None:
    class Foo:
        x: int = 0

    foo = Foo()
    ref, caller = _make_ref_and_caller(foo, foo.__setattr__, key="x", returns=None)
    del foo
    _assert_dead(ref, caller)


def test_weak_setitem_caller() -> None:
    class Foo:
        x: int = 0

        def __setitem__(self, key: str, value: int) -> None:
            assert key == "x"
            self.x = value

    foo = Foo()
    ref, caller = _make_ref_and_caller(foo, foo.__setitem__, key="x", returns=None)
    del foo
    _assert_dead(ref, caller)
