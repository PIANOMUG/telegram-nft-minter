import json
import aiofiles
from collections import defaultdict, deque
from pathlib import Path


class ConversationMemory:
    def __init__(self, memory_limit: int = 50):
        self.memory_limit = memory_limit
        self._servers = defaultdict(lambda: deque(maxlen=memory_limit))
        self._file = Path("data/memory.json")
        self._load()

    def _load(self):
        try:
            if self._file.exists():
                data = json.loads(self._file.read_text())
                for sid, msgs in data.items():
                    self._servers[int(sid)] = deque(msgs, maxlen=self.memory_limit)
        except Exception:
            pass

    def _save(self):
        try:
            self._file.parent.mkdir(parents=True, exist_ok=True)
            data = {str(sid): list(msgs) for sid, msgs in self._servers.items()}
            self._file.write_text(json.dumps(data, indent=2))
        except Exception:
            pass

    def add(self, server_id: int, role: str, content: str):
        self._servers[server_id].append({"role": role, "content": content})
        self._save()

    def get_context(self, server_id: int) -> list:
        return list(self._servers.get(server_id, []))

    def clear(self, server_id: int):
        self._servers.pop(server_id, None)
        self._save()
