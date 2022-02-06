"""MutableSequence that emits events when altered.

Note For Developers
===================

Be cautious when re-implementing typical list-like methods here (e.g. extend,
pop, clear, etc...).  By not re-implementing those methods, we force ALL "CRUD"
(create, read, update, delete) operations to go through a few key methods
defined by the abc.MutableSequence interface, where we can emit the necessary
events.

Specifically:

- `insert` = "create" : add a new item/index to the list
- `__getitem__` = "read" : get the value of an existing index
- `__setitem__` = "update" : update the value of an existing index
- `__delitem__` = "delete" : remove an existing index from the list

All of the additional list-like methods are provided by the MutableSequence
interface, and call one of those 4 methods.  So if you override a method, you
MUST make sure that all the appropriate events are emitted.  (Tests should
cover this in test_evented_list.py)
"""

from typing import (
    Any,
    Iterable,
    List,
    MutableSequence,
    Tuple,
    TypeVar,
    Union,
    cast,
    overload,
)

from .._signal import Signal

_T = TypeVar("_T")
Index = Union[int, slice]


class ListEvents:
    """Events available on EventedList.

    Attributes
    ----------
    events.inserting (index: int)
        emitted before an item is inserted at `index`
    events.inserted (index: int, value: T)
        emitted after `value` is inserted at `index`
    removing (index: int)
        emitted before an item is removed at `index`
    removed (index: int, value: T)
        emitted after `value` is removed at `index`
    moving (index: int, new_index: int)
        emitted before an item is moved from `index` to `new_index`
    moved (index: int, new_index: int, value: T)
        emitted after `value` is moved from `index` to `new_index`
    changed (index: int or slice, old_value: T or List[T], value: T or List[T])
        emitted when `index` is set from `old_value` to `value`
    reordered (value: self)
        emitted when the list is reordered (eg. moved/reversed).
    """

    inserting = Signal(int)  # idx
    inserted = Signal(int, object)  # (idx, value)
    removing = Signal(int)  # idx
    removed = Signal(int, object)  # (idx, value)
    moving = Signal(int, int)  # (src_idx, dest_idx)
    moved = Signal(tuple, object)  # ((src_idx, dest_idx), value)
    changed = Signal(object, object, object)  # (int | slice, old, new)
    reordered = Signal()


class EventedList(MutableSequence[_T]):
    """Mutable Sequence that emits events when altered.

    This class is designed to behave exactly like the builtin `list`, but
    will emit events before and after all mutations (insertion, removal,
    setting, and moving).

    Parameters
    ----------
    data : iterable, optional
        Elements to initialize the list with.
    """

    events: ListEvents

    def __init__(self, data: Iterable[_T] = ()):
        super().__init__()
        self.events = ListEvents()
        self._list: List[_T] = []
        self.extend(data)

    # WAIT!! ... Read the module docstring before reimplement these methods
    # def append(self, item): ...
    # def clear(self): ...
    # def pop(self, index=-1): ...
    # def extend(self, value: Iterable[_T]): ...
    # def remove(self, value: T): ...

    def insert(self, index: int, value: _T) -> None:
        """Insert `value` before index."""
        _value = self._pre_insert(value)
        self.events.inserting.emit(index)
        self._list.insert(index, _value)
        self.events.inserted.emit(index, value)

    @overload
    def __getitem__(self, key: int) -> _T:
        ...

    @overload
    def __getitem__(self, key: slice) -> "EventedList[_T]":
        ...

    def __getitem__(self, key: Index) -> Union[_T, "EventedList[_T]"]:
        result = self._list[key]
        return self.__newlike__(result) if isinstance(result, list) else result

    @overload
    def __setitem__(self, key: int, value: _T) -> None:
        ...

    @overload
    def __setitem__(self, key: slice, value: Iterable[_T]) -> None:
        ...

    def __setitem__(self, key: Index, value: Union[_T, Iterable[_T]]) -> None:
        """Set self[key] to value."""
        old = self._list[key]
        if value is old:
            return

        if isinstance(key, slice):
            if not isinstance(value, Iterable):
                raise TypeError("Can only assign an iterable to slice")

            value = [self._pre_insert(v) for v in value]  # before we mutate the list

            _ev_inserting = self.events.inserting
            _ev_inserted = self.events.inserted

            if key.step is not None:  # extended slices are more restricted
                indices = list(range(*key.indices(len(self))))
                if len(value) != len(indices):
                    raise ValueError(
                        f"attempt to assign sequence of size {len(value)} to extended "
                        "slice of size {len(indices)}",
                    )
                for i, v in zip(indices, value):
                    with _ev_inserting.blocked(), _ev_inserted.blocked():
                        self._list[i] = v
            else:
                del self[key]
                start = key.start or 0
                for i, v in enumerate(value):
                    with _ev_inserting.blocked(), _ev_inserted.blocked():
                        self.insert(start + i, v)
        else:
            self._list[key] = self._pre_insert(cast(_T, value))

        self.events.changed.emit(key, old, value)

    def __delitem__(self, key: Index) -> None:
        """Delete self[key]."""
        # delete from the end
        for parent, index in sorted(self._delitem_indices(key), reverse=True):
            parent.events.removing.emit(index)
            parent._pre_remove(index)
            item = parent._list.pop(index)
            self.events.removed.emit(index, item)

    def _delitem_indices(self, key: Index) -> Iterable[Tuple["EventedList[_T]", int]]:
        # returning List[(self, int)] allows subclasses to pass nested members
        if isinstance(key, int):
            return [(self, key if key >= 0 else key + len(self))]
        elif isinstance(key, slice):
            return [(self, i) for i in range(*key.indices(len(self)))]

        raise TypeError(
            f"EventedList indices must be integers or slices, not {type(key).__name__}"
        )

    def _pre_insert(self, value: _T) -> _T:
        return value

    def _pre_remove(self, index: int) -> None:
        # self._disconnect_child_emitters(self[index])
        pass

    def __newlike__(self, iterable: Iterable[_T]) -> "EventedList[_T]":
        """Return new instance of same class."""
        return self.__class__(iterable)

    def copy(self) -> "EventedList[_T]":
        """Return a shallow copy of the list."""
        return self.__newlike__(self)

    def __add__(self, other: Iterable[_T]) -> "EventedList[_T]":
        """Add other to self, return new object."""
        copy = self.copy()
        copy.extend(other)
        return copy

    def __iadd__(self, other: Iterable[_T]) -> "EventedList[_T]":
        """Add other to self in place (self += other)."""
        self.extend(other)
        return self

    def __radd__(self, other: List) -> List:
        """Reflected add (other + self).  Cast self to list."""
        return other + list(self)

    def __len__(self) -> int:
        """Return len(self)."""
        return len(self._list)

    def __repr__(self) -> str:
        """Return repr(self)."""
        return f"{type(self).__name__}({self._list})"

    def __eq__(self, other: Any) -> bool:
        """Return self==value."""
        return bool(self._list == other)

    def __hash__(self) -> int:
        # it's important to add this to allow this object to be hashable
        # given that we've also reimplemented __eq__
        return id(self)

    def reverse(self, *, emit_individual_events: bool = False) -> None:
        """Reverse list *IN PLACE*."""
        if emit_individual_events:
            super().reverse()
        else:
            self._list.reverse()
        self.events.reordered.emit(self)

    # def move(self, src_index: int, dest_index: int = 0) -> bool:
    #     """Insert object at `src_index` before `dest_index`.

    #     Both indices refer to the list prior to any object removal
    #     (pre-move space).
    #     """
    #     if dest_index < 0:
    #         dest_index += len(self) + 1
    #     if dest_index in (src_index, src_index + 1):
    #         # this is a no-op
    #         return False

    #     self.moving.emit((src_index, dest_index))
    #     item = self._list.pop(src_index)
    #     if dest_index > src_index:
    #         dest_index -= 1
    #     self._list.insert(dest_index, item)
    #     self.moved.emit((src_index, dest_index, item))
    #     self.reordered.emit(self)
    #     return True

    # def move_multiple(self, sources: Iterable[Index], dest_index: int = 0) -> int:
    #     """Move a batch of `sources` indices, to a single destination.

    #     Note, if `dest_index` is higher than any of the `sources`, then
    #     the resulting position of the moved objects after the move operation
    #     is complete will be lower than `dest_index`.

    #     Parameters
    #     ----------
    #     sources : Sequence[int or slice]
    #         A sequence of indices
    #     dest_index : int, optional
    #         The destination index.  All sources will be inserted before this
    #         index (in pre-move space), by default 0... which has the effect of
    #         "bringing to front" everything in `sources`, or acting as a
    #         "reorder" method if `sources` contains all indices.

    #     Returns
    #     -------
    #     int
    #         The number of successful move operations completed.

    #     Raises
    #     ------
    #     TypeError
    #         If the destination index is a slice, or any of the source indices
    #         are not `int` or `slice`.
    #     """

    #     # calling list here makes sure that there are no index errors up front
    #     move_plan = list(self._move_plan(sources, dest_index))

    #     # don't assume index adjacency ... so move objects one at a time
    #     # this *could* be simplified with an intermediate list ... but this way
    #     # allows any views (such as QtViews) to update themselves more easily.
    #     # If this needs to be changed in the future for performance reasons,
    #     # then the associated QtListView will need to changed from using
    #     # `beginMoveRows` & `endMoveRows` to using `layoutAboutToBeChanged` &
    #     # `layoutChanged` while *manually* updating model indices with
    #     # `changePersistentIndexList`.  That becomes much harder to do with
    #     # nested tree-like models.
    #     with self.reordered.blocked():
    #         for src, dest in move_plan:
    #             self.move(src, dest)

    #     self.reordered.emit(self)
    #     return len(move_plan)

    # def _move_plan(self, sources: Iterable[Index], dest_index: int):
    #     """Prepared indices for a multi-move.

    #     Given a set of `sources` from anywhere in the list,
    #     and a single `dest_index`, this function computes and yields
    #     `(from_index, to_index)` tuples that can be used sequentially in
    #     single move operations.  It keeps track of what has moved where and
    #     updates the source and destination indices to reflect the model at each
    #     point in the process.

    #     This is useful for a drag-drop operation with a QtModel/View.

    #     Parameters
    #     ----------
    #     sources : Iterable[tuple[int, ...]]
    #         An iterable of tuple[int] that should be moved to `dest_index`.
    #     dest_index : Tuple[int]
    #         The destination for sources.
    #     """
    #     if isinstance(dest_index, slice):
    #         raise TypeError(
    #             f"Destination index may not be a slice",
    #         )

    #     to_move: List[int] = []
    #     for idx in sources:
    #         if isinstance(idx, slice):
    #             to_move.extend(list(range(*idx.indices(len(self)))))
    #         elif isinstance(idx, int):
    #             to_move.append(idx)
    #         else:
    #             raise TypeError(
    #                 "Can only move integer or slice indices",
    #             )

    #     to_move = list(dict.fromkeys(to_move))

    #     if dest_index < 0:
    #         dest_index += len(self) + 1

    #     d_inc = 0
    #     popped: List[int] = []
    #     for i, src in enumerate(to_move):
    #         if src != dest_index:
    #             # we need to decrement the src_i by 1 for each time we have
    #             # previously pulled items out from in front of the src_i
    #             src -= sum(x <= src for x in popped)
    #             # if source is past the insertion point, increment src for each
    #             # previous insertion
    #             if src >= dest_index:
    #                 src += i
    #             yield src, dest_index + d_inc

    #         popped.append(src)
    #         # if the item moved up, icrement the destination index
    #         if dest_index <= src:
    #             d_inc += 1