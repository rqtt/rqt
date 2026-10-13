from dataclasses import dataclass

import psutil

# username is left out on purpose: on Windows it means opening every process
# token, which was the slowest part of each poll. It never changes for a
# running process, so it's looked up once and cached instead.
ATTRS = ["pid", "name", "memory_info", "num_threads", "status", "create_time"]


@dataclass(slots=True)
class ProcRow:
    pid: int
    name: str
    user: str
    cpu: float
    rss: int
    mem_pct: float
    threads: int
    status: str


class ProcessTable:
    """
    psutil.process_iter() keeps its Process objects around between calls, which
    is what makes cpu_percent(None) meaningful here: it reports usage since the
    previous poll. The very first poll therefore shows 0% for everything.
    """

    def __init__(self):
        self.ncpu = psutil.cpu_count() or 1
        self._users = {}   # (pid, create_time) -> username

    def _user(self, proc, key):
        user = self._users.get(key)
        if user is None:
            try:
                user = proc.username() or ""
            except (psutil.Error, OSError):
                user = ""
            if "\\" in user:  # DOMAIN\user on Windows
                user = user.split("\\", 1)[1]
            self._users[key] = user
        return user

    def poll(self):
        total_mem = psutil.virtual_memory().total
        rows, alive = [], set()
        for p in psutil.process_iter(ATTRS, ad_value=None):
            info = p.info
            key = (info["pid"], info.get("create_time"))
            alive.add(key)
            try:
                cpu = p.cpu_percent(None) / self.ncpu
            except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
                cpu = 0.0
            mi = info.get("memory_info")
            rss = mi.rss if mi else 0
            rows.append(ProcRow(
                pid=info["pid"],
                name=info.get("name") or f"pid {info['pid']}",
                user=self._user(p, key),
                cpu=cpu,
                rss=rss,
                mem_pct=100.0 * rss / total_mem if total_mem else 0.0,
                threads=info.get("num_threads") or 0,
                status=info.get("status") or "",
            ))
        # forget processes that have exited
        if len(self._users) > len(alive) + 200:
            self._users = {k: v for k, v in self._users.items() if k in alive}
        return rows
