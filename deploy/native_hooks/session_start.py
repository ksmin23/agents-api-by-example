"""Codex command-hook protocol adapter. Manual replay is not a native dispatch test."""
import json
import os
import sys
import time
import urllib.request

def make_record(payload):
    event = payload.get('hook_event_name')
    if event != 'SessionStart':
        raise ValueError('unexpected_hook')
    sid = payload.get('session_id')
    if not isinstance(sid, str) or not 1 <= len(sid) <= 160:
        raise ValueError('invalid_session_id')
    return {'hook_event_name': event, 'session_id': sid, 'source': 'codex_command_hook'}

if __name__ == '__main__':
    raw = sys.stdin.buffer.read(16385)
    if len(raw) > 16384:
        raise SystemExit('hook_payload_too_large')
    record = make_record(json.loads(raw))
    body = {'resourceLogs': [{'resource': {'attributes': [
        {'key': 'service.name', 'value': {'stringValue': 'tutorial.native-hook-adapter'}}]},
        'scopeLogs': [{'scope': {'name': 'tutorial.hooks'}, 'logRecords': [{
            'timeUnixNano': str(time.time_ns()), 'severityText': 'INFO',
            'body': {'stringValue': record['hook_event_name']},
            'attributes': [{'key': k, 'value': {'stringValue': v}} for k, v in record.items()]
        }]}]}]}
    endpoint = os.environ['TUTORIAL_OTLP_LOGS_ENDPOINT']
    req = urllib.request.Request(endpoint, data=json.dumps(body).encode(),
                                 headers={'Content-Type': 'application/json'})
    with urllib.request.urlopen(req, timeout=5) as response:
        if response.status != 200:
            raise SystemExit('otlp_export_failed')
    # No prompt, command, cwd, environment, or username is exported.
