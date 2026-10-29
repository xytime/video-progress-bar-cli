"""隔离测试工具的内核父子归属记录；不按名称、路径或生产 PID 猜测归属。

# Modification History
| Version | Date | Author | Description |
| --- | --- | --- | --- |
| 1.0.0 | 2026-10-29 | Codex | 记录后代 birth，回收已观察到的独立会话；PID 重用与未知归属拒绝发送信号。 |
"""
import ctypes
import os
import signal
import sys
import time


class BSDInfo(ctypes.Structure):
    _fields_ = [('prefix', ctypes.c_uint32 * 12), ('comm', ctypes.c_char * 16),
                ('name', ctypes.c_char * 32), ('tail', ctypes.c_uint32 * 6),
                ('seconds', ctypes.c_uint64), ('micros', ctypes.c_uint64)]


class ProcessTree:
    def __init__(self, pid):
        if sys.platform != 'darwin':
            raise RuntimeError('隔离进程归属只支持 macOS')
        self.lib = ctypes.CDLL('/usr/lib/libproc.dylib', use_errno=True)
        self.lib.proc_pidinfo.argtypes = [ctypes.c_int, ctypes.c_int, ctypes.c_uint64, ctypes.c_void_p, ctypes.c_int]
        self.lib.proc_listchildpids.argtypes = [ctypes.c_int, ctypes.c_void_p, ctypes.c_int]
        self.owners = {}
        row = self.info(pid)
        if row is not None:
            self.owners[pid] = self.birth(row)

    def info(self, pid):
        row = BSDInfo()
        if self.lib.proc_pidinfo(pid, 3, 0, ctypes.byref(row), ctypes.sizeof(row)) != ctypes.sizeof(row):
            return None
        return row if row.prefix[3] == pid and row.prefix[1] != 5 else None

    @staticmethod
    def birth(row):
        return (row.seconds, row.micros)

    def owned(self, pid):
        row = self.info(pid)
        return row is not None and self.birth(row) == self.owners.get(pid)

    def capture(self):
        pending = list(self.owners)
        seen = set()
        while pending:
            parent = pending.pop()
            if parent in seen or not self.owned(parent):
                continue
            seen.add(parent)
            size = self.lib.proc_listchildpids(parent, None, 0)
            if size <= 0:
                continue
            values = (ctypes.c_int * (size + 32))()
            used = self.lib.proc_listchildpids(parent, values, ctypes.sizeof(values))
            for pid in list(values)[:max(0, used)]:
                row = self.info(pid)
                # child 查询后再次核实内核 ppid 和父进程 birth，拒绝 PID 重用。
                if pid > 0 and row is not None and row.prefix[4] == parent and self.owned(parent):
                    birth = self.birth(row)
                    if pid in self.owners and self.owners[pid] != birth:
                        continue
                    self.owners[pid] = birth
                    pending.append(pid)

    def cleanup(self):
        self.capture()
        killed = []
        for pid in reversed(list(self.owners)):
            if self.owned(pid):
                try:
                    os.kill(pid, signal.SIGKILL)
                    killed.append(pid)
                except ProcessLookupError:
                    pass
        deadline = time.monotonic() + 3
        while any(self.owned(pid) for pid in killed) and time.monotonic() < deadline:
            time.sleep(.02)
        remaining = [pid for pid in self.owners if self.owned(pid)]
        return dict(observed=len(self.owners), killed=killed, remaining=remaining,
                    scope='内核父子链实际观察并绑定 birth；不声称覆盖未被观察的瞬时双重 fork')
