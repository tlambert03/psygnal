from dataclasses import dataclass

from psygnal import evented
from psygnal.containers import EventedList


@evented
@dataclass
class M:
    a: EventedList[int]


m = M(a=EventedList([1, 2, 3]))
m.events.connect(lambda info: print(info))
m.a = [12]
