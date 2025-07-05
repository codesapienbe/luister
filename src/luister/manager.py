from __future__ import annotations

"""Simple singleton to track open widgets and close them on quit."""

import weakref
from typing import List
from PyQt6.QtCore import QObject

class _Manager(QObject):
    def __init__(self):
        super().__init__()
        self._widgets: List[weakref.ReferenceType] = []

    def register(self, widget):  # type: ignore
        if widget is None:
            return
        self._widgets.append(weakref.ref(widget))

    def shutdown(self):
        for ref in list(self._widgets):
            w = ref()
            if w is not None:
                try:
                    w.close()
                except Exception:
                    pass
        self._widgets.clear()

_manager = _Manager()

def get_manager() -> _Manager:  # type: ignore[name-defined]
    return _manager 