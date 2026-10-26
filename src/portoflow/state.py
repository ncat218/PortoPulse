"""Local atomic-state helpers and resource ceilings."""
import hashlib, json, time
from pathlib import Path

def digest(value):
    return hashlib.sha256(json.dumps(value,sort_keys=True,default=str).encode()).hexdigest()

def state_get(connection,key,default=None):
    row=connection.execute('SELECT value FROM state WHERE key=?',(key,)).fetchone()
    return json.loads(row[0]) if row else default

def state_set(connection,key,value):
    connection.execute('INSERT OR REPLACE INTO state VALUES (?,?)',(key,json.dumps(value,sort_keys=True)))

def guard_resources(root,plan,deadline=None,*,check_disk=True):
    if deadline is not None and time.monotonic()>=deadline:
        raise TimeoutError('Processing deadline reached; committed checkpoints retained')
    try:
        import resource
        rss=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss/1024
        if rss>plan['max_rss_mb']:
            raise MemoryError(f'RSS ceiling exceeded: {rss:.0f} MiB')
    except ImportError:
        pass
    # Called per batch, not per record. Native subprocess also has a hard timeout.
    if check_disk and sum(p.stat().st_size for p in Path(root).rglob('*') if p.is_file())>plan['max_output_gb']*1024**3:
        raise OSError('Output disk ceiling exceeded; retain checkpoints and stop')
