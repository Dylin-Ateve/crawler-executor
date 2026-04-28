from __future__ import annotations

import os


class EnvSettings:
    def get(self, name: str, default=None):
        return os.getenv(name, default)

    def getint(self, name: str, default: int = 0) -> int:
        value = os.getenv(name)
        if value in (None, ""):
            return default
        return int(value)
