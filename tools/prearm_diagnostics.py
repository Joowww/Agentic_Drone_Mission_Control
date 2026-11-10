"""Internal read-only Trigger client diagnostics. No operations on import.

AP_DDS Trigger_Response has boolean success and string message. Parse the ROS
CLI representation with a restricted AST, never eval, grep or inferred reasons.
"""
import argparse
import ast
import codecs
from datetime import datetime, timezone
import json
import re
import subprocess
import threading
import time

SERVICE_TYPE = 'std_srvs/srv/Trigger'
SERVICE_TIMEOUT_S = 30
EVENT_PREFIX = 'TFG_PREARM_EVENT '


def parse_response(stdout):
    # Require a response envelope: request/log text containing success=True is not evidence.
    match = re.search(r'^response:\s*\n', stdout, re.M)
    if not match:
        return None
    try:
        node = ast.parse(stdout[match.end():].strip(), mode='eval').body
        if (not isinstance(node, ast.Call) or node.args
                or ast.unparse(node.func) not in {
                    'std_srvs.srv.Trigger_Response', 'std_srvs.srv._trigger.Trigger_Response',
                    'Trigger_Response'}):
            return None
        fields = {k.arg: ast.literal_eval(k.value) for k in node.keywords}
        if len(node.keywords) != 2 or set(fields) != {'success', 'message'}:
            return None
        if type(fields['success']) is not bool or not isinstance(fields['message'], str):
            return None
        return fields
    except (SyntaxError, ValueError, TypeError, RecursionError):
        return None


def classify(return_code, stdout, stderr, *, timed_out=False, execution_error=None):
    response = parse_response(stdout)
    wrapper_timeout = (return_code == 124 and
                       'timeout: sending signal TERM to command' in stderr)
    if timed_out or wrapper_timeout:
        outcome = 'TIMEOUT'
    elif execution_error:
        outcome = 'EXECUTION_ERROR'
    elif return_code != 0:
        unavailable = re.search(r'\bservice (?:is )?not available\b|\bservice unavailable\b',
                                stdout + '\n' + stderr, re.I)
        outcome = 'SERVICE_UNAVAILABLE' if unavailable else 'EXECUTION_ERROR'
    elif response is None:
        outcome = 'UNINTERPRETABLE_RESPONSE'
    else:
        outcome = 'ACCEPTED' if response['success'] else 'NEGATIVE_RESPONSE'
    return {'outcome': outcome, 'response': response,
            'timed_out': bool(timed_out or wrapper_timeout),
            'timeout_basis': ('local_client_deadline' if timed_out else
                              'timeout_wrapper_diagnostic' if wrapper_timeout else None),
            'waiting_for_service_observed': 'waiting for service to become available' in stdout.lower()}


def run_attempt(service, attempt, emit, *, command=None, timeout_s=SERVICE_TIMEOUT_S):
    if not re.fullmatch(r'/ap/v[1-9][0-9]*/prearm_check', service) or not 1 <= attempt <= 18:
        raise ValueError('Invalid prearm service or attempt')
    command = command or [
        'docker', 'exec', 'tfg-ardupilot-gazebo', 'bash', '-lc',
        'source /opt/ros/humble/setup.bash && source /root/ardu_ws/install/setup.bash && '
        'LC_ALL=C timeout --verbose 30 ros2 service call "$1" std_srvs/srv/Trigger "{}"',
        'bash', service,
    ]
    started = time.monotonic()
    base = {'service': service, 'interface': service.split('/')[2], 'attempt': attempt,
            'service_type': SERVICE_TYPE, 'request': '{}', 'command': command,
            'timeout_s': timeout_s, 'started_at_utc': datetime.now(timezone.utc).isoformat(),
            'started_monotonic_s': started}
    emit({**base, 'event': 'started'})
    chunks = {'stdout': [], 'stderr': []}
    closed = {'stdout': False, 'stderr': False}
    lock = threading.Lock()

    def read_stream(name, pipe):
        decoder = codecs.getincrementaldecoder('utf-8')(errors='replace')
        try:
            while data := pipe.read1(4096):
                text = decoder.decode(data)
                with lock:
                    chunks[name].append(data)
                    emit({**base, 'event': 'output', 'stream': name, 'text': text,
                          'received_monotonic_s': time.monotonic()})
            tail = decoder.decode(b'', final=True)
            if tail:
                with lock:
                    emit({**base, 'event': 'output', 'stream': name, 'text': tail,
                          'received_monotonic_s': time.monotonic()})
        finally:
            closed[name] = True
            pipe.close()

    code = None
    timed_out = False
    error = None
    threads = []
    try:
        process = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        for name in ('stdout', 'stderr'):
            thread = threading.Thread(target=read_stream, args=(name, getattr(process, name)), daemon=True)
            thread.start()
            threads.append(thread)
        try:
            code = process.wait(timeout=timeout_s)
        except subprocess.TimeoutExpired:
            timed_out = True
            process.kill()  # local read-only Docker client, never a vehicle process
            code = process.wait()
        for thread in threads:
            thread.join(timeout=0.2)
    except OSError as exc:
        error = f'{type(exc).__name__}: {exc}'
    with lock:
        stdout, stderr = (b''.join(chunks[name]).decode('utf-8', errors='replace')
                          for name in ('stdout', 'stderr'))
        result = {**base, 'event': 'completed', 'return_code': code,
                  'stdout': stdout, 'stderr': stderr, 'execution_error': error,
                  'streams_closed': dict(closed),
                  'finished_at_utc': datetime.now(timezone.utc).isoformat(),
                  'duration_wall_s': time.monotonic() - started,
                  **classify(code, stdout, stderr, timed_out=timed_out, execution_error=error)}
        if not all(closed.values()) and error is None:
            result.update(outcome='INCOMPLETE_CAPTURE')
        emit(result)
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--service', required=True)
    parser.add_argument('--attempt', required=True, type=int)
    args = parser.parse_args()
    def emit(record):
        print(EVENT_PREFIX + json.dumps(record, ensure_ascii=False), flush=True)
    result = run_attempt(args.service, args.attempt, emit)
    return 0 if result['outcome'] == 'ACCEPTED' else 1


if __name__ == '__main__':
    raise SystemExit(main())
