"""Read-only runtime metrics; no credentials or external model requests."""
import asyncio
import os
from pathlib import Path
import shutil
import time
from datetime import datetime, timezone

from sqlalchemy import text
from app.api.health import dependencies
from app.core.database import engine

_started = time.monotonic()
_lock = asyncio.Lock()
_cached = None
_sampled = 0.0


def _read(path):
    try:
        return Path(path).read_text().strip()
    except OSError:
        return None


def _integer(path):
    try:
        return int(_read(path))
    except (TypeError, ValueError):
        return None


def _cpu_ticks():
    value = _read('/proc/stat')
    if not value:
        return None
    try:
        ticks = [int(n) for n in value.splitlines()[0].split()[1:9]]
        return sum(ticks), ticks[3] + ticks[4]
    except (IndexError, ValueError):
        return None


def _memory():
    fields = {}
    for line in (_read('/proc/meminfo') or '').splitlines():
        parts = line.split()
        if len(parts) >= 2:
            try:
                fields[parts[0].rstrip(':')] = int(parts[1]) * 1024
            except ValueError:
                pass
    total, available = fields.get('MemTotal'), fields.get('MemAvailable')
    used = max(0, total - available) if total and available is not None else None
    current = _integer('/sys/fs/cgroup/memory.current')
    limit = _integer('/sys/fs/cgroup/memory.max')
    if current is None:
        current = _integer('/sys/fs/cgroup/memory/memory.usage_in_bytes')
        limit = _integer('/sys/fs/cgroup/memory/memory.limit_in_bytes')
    # cgroup v1 uses a huge integer when no memory limit is configured.
    if limit is not None and (limit <= 0 or limit >= (1 << 60)):
        limit = None
    return {'total_bytes': total, 'used_bytes': used,
            'percent': round(used / total * 100, 1) if total and used is not None else None,
            'container_used_bytes': current, 'container_limit_bytes': limit}


def _uptime():
    try:
        # /proc/self/stat field 22: process start time in clock ticks since boot.
        fields = _read('/proc/self/stat').rsplit(')', 1)[1].split()
        boot_seconds = float(_read('/proc/uptime').split()[0])
        return max(0, int(boot_seconds - int(fields[19]) / os.sysconf('SC_CLK_TCK')))
    except (AttributeError, IndexError, TypeError, ValueError, OSError):
        return int(time.monotonic() - _started)


async def _processes():
    process = None
    try:
        process = await asyncio.create_subprocess_exec(
            'supervisorctl', 'status', stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.DEVNULL)
        output, _ = await asyncio.wait_for(process.communicate(), 3)
        result = {}
        for line in output.decode(errors='replace').splitlines():
            parts = line.split()
            if len(parts) >= 2:
                result[parts[0]] = parts[1]
        return {**_observed_processes(), **{k: v for k, v in result.items() if k in ('nginx', 'uvicorn', 'postgresql', 'redis')}}
    except (OSError, asyncio.TimeoutError):
        if process and process.returncode is None:
            process.kill()
            await process.wait()
        return _observed_processes()


def _observed_processes():
    result = {}
    try:
        for path in Path('/proc').iterdir():
            if not path.name.isdigit():
                continue
            state = _read(path / 'stat')
            if not state or state.rsplit(')', 1)[-1].split()[0] in ('Z', 'X'):
                continue
            name = _read(path / 'comm')
            key = {'nginx': 'nginx', 'postgres': 'postgresql', 'redis-server': 'redis'}.get(name)
            if key:
                result[key] = 'RUNNING'
            if name in ('python', 'python3', 'uvicorn'):
                command = _read(path / 'cmdline') or ''
                if 'app.services.serve' in command or name == 'uvicorn':
                    result['uvicorn'] = 'RUNNING'
    except (OSError, IndexError):
        pass
    return result


async def snapshot():
    global _cached, _sampled
    async with _lock:
        if _cached is not None and time.monotonic() - _sampled < 5:
            return _cached
        first = _cpu_ticks()
        checks_task = asyncio.create_task(asyncio.wait_for(dependencies(), 5))
        processes_task = asyncio.create_task(_processes())
        await asyncio.sleep(.2)
        last = _cpu_ticks()
        cpu_percent = None
        if first and last and last[0] > first[0]:
            cpu_percent = round(max(0, min(100, 100 * (1 - (last[1] - first[1]) / (last[0] - first[0])))), 1)
        try:
            checks = await checks_task
        except Exception:
            checks = {'fastapi': 'ok', 'postgresql': 'unknown', 'redis': 'unknown', 'disk': 'unknown'}
        processes = await processes_task
        components = []
        for key, label, process_name in [('nginx', 'Web 服务', 'nginx'), ('fastapi', 'API 服务', 'uvicorn'),
                                         ('postgresql', 'PostgreSQL', 'postgresql'), ('redis', 'Redis', 'redis')]:
            state = processes.get(process_name)
            check = checks.get(key)
            status = ('error' if state is not None and state != 'RUNNING' else
                      'ok' if check == 'ok' or key == 'nginx' and state == 'RUNNING' else
                      'error' if check == 'error' else 'unknown')
            components.append({'name': label, 'status': status,
                               'detail': '服务可用' if status == 'ok' else '检查失败' if status == 'error' else '暂时无法确认',
                               'process_state': state})
        try:
            async with asyncio.timeout(3):
                async with engine.connect() as connection:
                    version = await connection.scalar(text("SELECT extversion FROM pg_extension WHERE extname='vector'"))
            components.append({'name': 'pgvector', 'status': 'ok' if version else 'error',
                               'detail': '版本 ' + version if version else '未安装'})
        except Exception:
            components.append({'name': 'pgvector', 'status': 'unknown', 'detail': '暂时无法确认'})
        from app.services.external_logs import status as external_status
        try:
            es = await asyncio.wait_for(external_status(), 3)
            components.append({'name': 'Elasticsearch 日志',
                               'status': 'warning' if es.get('enabled') and es.get('failure_since') else 'info',
                               'detail': '持续写入失败' if es.get('enabled') and es.get('failure_since') else
                                         '已启用；连接检查请使用 Elasticsearch 页签' if es.get('enabled') else '未启用'})
        except Exception:
            components.append({'name': 'Elasticsearch 日志', 'status': 'unknown', 'detail': '暂时无法确认'})
        try:
            disk = shutil.disk_usage('/data')
            storage = {'total_bytes': disk.total, 'used_bytes': disk.used, 'free_bytes': disk.free,
                       'percent': round(disk.used / disk.total * 100, 1), 'status': checks.get('disk', 'unknown')}
        except OSError:
            storage = {'status': 'unknown'}
        try:
            load = [round(n, 2) for n in os.getloadavg()]
        except OSError:
            load = None
        cpu_max = (_read('/sys/fs/cgroup/cpu.max') or '').split()
        quota = _integer('/sys/fs/cgroup/cpu/cpu.cfs_quota_us')
        period = _integer('/sys/fs/cgroup/cpu/cpu.cfs_period_us')
        try:
            if len(cpu_max) == 2:
                quota, period = int(cpu_max[0]), int(cpu_max[1])
        except ValueError:
            quota = None
        cpu_limit = round(quota / period, 2) if quota and quota > 0 and period and period > 0 else None
        _cached = {'checked_at': datetime.now(timezone.utc).isoformat(),
                   'uptime_seconds': _uptime(),
                   'cpu': {'percent': cpu_percent, 'cores': os.cpu_count(), 'load': load, 'container_limit_cores': cpu_limit},
                   'memory': _memory(), 'disk': storage, 'components': components}
        _sampled = time.monotonic()
        return _cached
