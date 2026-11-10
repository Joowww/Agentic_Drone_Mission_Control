"""One reviewed socket-diagnostic budget. No environment or runtime overrides."""
from dataclasses import asdict, dataclass
import io
import json
import math
import os
from pathlib import Path
import stat


@dataclass(frozen=True)
class SocketBudget:
    reads: int = 2048
    row_bytes: int = 256 * 1024  # entire UTF-8 JSON record INCLUDING newline
    observations: int = 64
    journal_bytes: int = 16 * 1024 * 1024
    interval_s: float = 5.0
    cooperative_s: float = .25
    query_timeout_s: float = .75
    monitor_s: float = 600.0

    def __post_init__(self):
        for key, ceiling in [('reads',2048),('row_bytes',256*1024),
                             ('observations',64),('journal_bytes',16*1024*1024)]:
            v=getattr(self,key)
            if type(v) is not int or not 0<v<=ceiling:
                raise ValueError('Invalid socket budget '+key)
        for key in ('interval_s','cooperative_s','query_timeout_s','monitor_s'):
            v=getattr(self,key)
            ceiling={'interval_s':5.,'cooperative_s':.25,'query_timeout_s':.75,'monitor_s':600.}[key]
            if (type(v) not in (int,float) or not math.isfinite(v) or not 0<v<=ceiling
                    or key=='interval_s' and v!=5.):
                raise ValueError('Invalid socket budget '+key)
        if (self.row_bytes*self.observations>self.journal_bytes or
                self.cooperative_s>=self.query_timeout_s or
                self.query_timeout_s>=self.interval_s or self.interval_s>=self.monitor_s):
            raise ValueError('Incoherent socket budget')

    def record(self):
        return {'schema':'tfg.socket-budget/1',**asdict(self)}


SOCKET = SocketBudget()


def journal_rows(source):
    """Bounded file/bytes reader. Count framing before parsing; no unbounded read.

    A path is preferred: oversized files are rejected by fstat before reading.
    Bytes are retained only for compatibility with already-bounded offline callers.
    Files growing after fstat still encounter per-row/aggregate/count checks.
    """
    if isinstance(source,bytes):
        if len(source)>SOCKET.journal_bytes:raise ValueError('Socket journal byte budget exceeded')
        stream=io.BytesIO(source)
    elif isinstance(source,(str,os.PathLike)):
        fd=os.open(Path(source),os.O_RDONLY|os.O_NOFOLLOW|os.O_NONBLOCK)
        try:
            info=os.fstat(fd)
            if not stat.S_ISREG(info.st_mode) or info.st_size>SOCKET.journal_bytes:
                raise ValueError('Socket journal nonregular or byte budget exceeded')
            stream=os.fdopen(fd,'rb');fd=None
        finally:
            if fd is not None:os.close(fd)
    else:raise ValueError('Socket journal requires bytes or regular path')
    with stream:
        total=count=0
        while True:
            line=stream.readline(SOCKET.row_bytes+1)
            if not line:break
            total+=len(line);count+=1
            if total>SOCKET.journal_bytes or count>SOCKET.observations:
                raise ValueError('Socket journal aggregate/count budget exceeded')
            if len(line)>SOCKET.row_bytes or not line.endswith(b'\n') or line==b'\n':
                raise ValueError('Socket record truncated/empty or row budget exceeded')
            yield line
        if not count:raise ValueError('Empty socket journal')


def encode_row(value):
    """Producer framing, shared with persistence. Oversize is never emitted."""
    data=json.dumps(value,separators=(',',':')).encode()+b'\n'
    if len(data)>SOCKET.row_bytes:raise ValueError('Socket framed row budget exceeded')
    return data
