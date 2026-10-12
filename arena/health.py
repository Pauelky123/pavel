"""Worker readiness for monitors/containers. Does not fabricate success."""
import json
from .store import Store

if __name__ == '__main__':
    system = Store().snapshot()['system']
    print(json.dumps({k: system.get(k) for k in ('status', 'ready', 'heartbeat', 'last_cycle', 'current_error')}, ensure_ascii=False))
    raise SystemExit(0 if system['ready'] else 1)
