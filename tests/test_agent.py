import importlib.machinery
import importlib.util
import os
import json
import socket
import struct
import tempfile
import subprocess
import sys
import select
import threading
import time
from unittest import mock
from pathlib import Path
import unittest

AGENT = Path(__file__).resolve().parents[1] / 'agent' / 'herdr-bridge-agent'


def load_agent():
    loader = importlib.machinery.SourceFileLoader('bridge_agent', str(AGENT))
    spec = importlib.util.spec_from_loader(loader.name, loader)
    module = importlib.util.module_from_spec(spec)
    loader.exec_module(module)
    return module


def tcp_row(address='0100007F', port=5173, inode=123, state='0A', uid=None):
    return f' 0: {address}:{port:04X} 00000000:0000 {state} 00000000:00000000 00:00000000 00000000 {os.getuid() if uid is None else uid} 0 {inode} 1\n'


class FixtureAPI:
    def __init__(self, pid, pane='w1:p1'):
        self.pid, self.pane = pid, pane
        self.calls = []

    def call(self, method, params, expected):
        self.calls.append((method, params))
        if method == 'pane.list':
            return {'type': 'pane_list', 'panes': [{'pane_id': self.pane, 'cwd': '/src/demo\n\x1b\u202e'}]}
        return {'type': 'pane_process_info', 'process_info': {'pane_id': self.pane, 'foreground_processes': [{'pid': self.pid, 'name': 'server'}]}}


def proc_fixture(root, pid, parent=1, children='', inode=None, uid=None, namespace='host', cgroup='0::/user.slice'):
    p = root / str(pid)
    (p / 'fd').mkdir(parents=True)
    (p / 'task' / str(pid)).mkdir(parents=True)
    (p / 'ns').mkdir()
    for ns in ('net', 'pid', 'mnt'):
        (p / 'ns' / ns).symlink_to(f'{ns}:[{namespace}]')
    u = os.getuid() if uid is None else uid
    (p / 'status').write_text(f'Name:\tserver\nUid:\t{u}\t{u}\t{u}\t{u}\n')
    (p / 'stat').write_text(f'{pid} (a process) S {parent} ' + '0 ' * 17 + '12345 0\n')
    (p / 'cgroup').write_text(cgroup)
    (p / 'task' / str(pid) / 'children').write_text(children)
    if inode:
        (p / 'fd' / '3').symlink_to(f'socket:[{inode}]')
    return p


class AgentTests(unittest.TestCase):
    def test_fixture_foreground_tree_not_unrelated_uid_or_container(self):
        a = load_agent()
        self.assertTrue(hasattr(a, 'detect'), 'full detection is missing')
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            proc_fixture(root, 'self')
            proc_fixture(root, 10, children='11 12 13 14 15')
            proc_fixture(root, 11, parent=10, inode=101)
            proc_fixture(root, 12, parent=10, inode=102, uid=os.getuid()+1)
            proc_fixture(root, 13, parent=10, inode=103, namespace='container')
            proc_fixture(root, 14, parent=10, inode=104, cgroup='0::/docker/abcd')
            proc_fixture(root, 15, parent=99, inode=105)  # stale child entry
            proc_fixture(root, 99, inode=199)  # must never be a candidate
            (root / 'net').mkdir()
            (root / 'net' / 'tcp').write_text(''.join(tcp_row(port=5000+i, inode=i) for i in (101,102,103,104,105,199)))
            (root / 'net' / 'tcp6').write_text('')
            api = FixtureAPI(10)
            snapshot = a.detect(api, root)
            self.assertEqual(snapshot['type'], 'snapshot')
            self.assertEqual(len(snapshot['services']), 1)
            service = snapshot['services'][0]
            self.assertEqual((service['host'], service['port'], service['pane']), ('127.0.0.1', 5101, 'w1:p1'))
            self.assertEqual(service['project'], 'demo')
            self.assertRegex(service['id'], r'^[A-Za-z0-9_.:-]{1,128}$')
            self.assertEqual(a.detect(api, root), snapshot)
            self.assertEqual(api.calls[1], ('pane.process_info', {'pane_id': 'w1:p1'}))

    def test_real_spawned_loopback_server(self):
        a = load_agent()
        self.assertTrue(hasattr(a, 'detect'), 'full detection is missing')
        code = 'import socket,time; s=socket.socket(); s.bind(("127.0.0.1",0)); s.listen(); print(s.getsockname()[1],flush=True); time.sleep(30)'
        process = subprocess.Popen([sys.executable, '-c', code], stdout=subprocess.PIPE, text=True)
        try:
            port = int(process.stdout.readline())
            snapshot = a.detect(FixtureAPI(process.pid))
            self.assertEqual([(s['host'], s['port']) for s in snapshot['services']], [('127.0.0.1', port)])
        finally:
            process.terminate()
            process.wait(timeout=5)
            process.stdout.close()

    def test_socket_request_and_security_boundaries(self):
        a = load_agent()
        self.assertTrue(hasattr(a, 'HerdrClient'), 'bounded Herdr client is missing')
        with tempfile.TemporaryDirectory() as tmp:
            path = str(Path(tmp) / 'api.sock')
            with socket.socket(socket.AF_UNIX) as listener:
                listener.bind(path)
                stream = mock.MagicMock()
                stream.__enter__.return_value = stream
                stream.getsockopt.return_value = struct.pack('3i', 42, os.getuid(), os.getgid())
                good = {'id': 'bridge', 'result': {'type': 'pane_list', 'panes': []}}
                with mock.patch.object(a.socket, 'socket', return_value=stream):
                    stream.recv.return_value = (json.dumps(good)+'\n').encode()
                    client = a.HerdrClient(path)
                    self.assertEqual(client.call('pane.list', {}, 'pane_list'), good['result'])
                    request = json.loads(stream.sendall.call_args.args[0])
                    self.assertEqual(request, {'id': 'bridge', 'method': 'pane.list', 'params': {}})
                    for response in [
                        {'id': 'bridge', 'error': {'code': 'unsupported', 'message': 'bad\napi'}},
                        {'id': 'other', 'result': good['result']},
                        {'id': 'bridge', 'result': {'type': 'pane_process_info'}},
                        {'id': 'bridge', 'result': []},
                    ]:
                        stream.recv.return_value = (json.dumps(response)+'\n').encode()
                        with self.assertRaises(a.DetectorError):
                            client.call('pane.list', {}, 'pane_list')
                    stream.recv.return_value = b'x' * (a.MAX_API_BYTES+1)
                    with self.assertRaises(a.DetectorError):
                        client.call('pane.list', {}, 'pane_list')
                    stream.getsockopt.return_value = struct.pack('3i', 42, os.getuid()+1, 0)
                    with self.assertRaises(a.DetectorError):
                        client.call('pane.list', {}, 'pane_list')
                    with self.assertRaises(a.DetectorError):
                        client.call('pane.send_text', {}, 'ok')
            regular = Path(tmp) / 'regular'
            regular.touch()
            with self.assertRaises(a.DetectorError):
                a.HerdrClient(str(regular)).call('pane.list', {}, 'pane_list')

    def test_real_unix_socket_watch_heartbeats(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = str(Path(tmp) / 'herdr.sock')
            requests, failures = [], []
            with socket.socket(socket.AF_UNIX) as server:
                server.bind(path)
                server.listen(2)
                server.settimeout(6)
                def serve():
                    try:
                        for _ in range(2):
                            with server.accept()[0] as conn:
                                conn.settimeout(2)
                                request = json.loads(conn.recv(4096))
                                requests.append(request)
                                conn.sendall((json.dumps({'id': request['id'], 'result': {'type': 'pane_list', 'panes': []}})+'\n').encode())
                    except Exception as exc:
                        failures.append(exc)
                thread = threading.Thread(target=serve)
                thread.start()
                child = subprocess.Popen([str(AGENT), '--watch'], env={**os.environ, 'HERDR_SOCKET_PATH': path}, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
                try:
                    frames, stamps = [], []
                    for _ in range(2):
                        self.assertTrue(select.select([child.stdout], [], [], 6)[0], 'no heartbeat within deadline')
                        frames.append(json.loads(child.stdout.readline()))
                        stamps.append(time.monotonic())
                    self.assertEqual(frames, [{'version': 1, 'type': 'snapshot', 'services': []}]*2)
                    self.assertGreater(stamps[1]-stamps[0], 2.5)
                    self.assertLess(stamps[1]-stamps[0], 4)
                finally:
                    child.terminate()
                    _, stderr = child.communicate(timeout=5)
                    thread.join(timeout=7)
                self.assertEqual(stderr, b'')
                self.assertFalse(failures)
                self.assertEqual([r['method'] for r in requests], ['pane.list']*2)

    def test_socket_timeout_and_owner_check(self):
        a = load_agent()
        with tempfile.TemporaryDirectory() as tmp:
            path = str(Path(tmp) / 'herdr.sock')
            with socket.socket(socket.AF_UNIX) as server:
                server.bind(path)
                server.listen(1)
                started = time.monotonic()
                with self.assertRaises(TimeoutError):
                    a.HerdrClient(path).call('pane.list', {}, 'pane_list')
                self.assertLess(time.monotonic()-started, 1.5)
                link = Path(tmp) / 'linked'
                link.symlink_to(path)
                with self.assertRaises(a.DetectorError):
                    a.HerdrClient(link).call('pane.list', {}, 'pane_list')
                real_stat = os.lstat(path)
                fake_stat = mock.Mock(st_mode=real_stat.st_mode, st_uid=os.getuid()+1)
                with mock.patch.object(a.os, 'lstat', return_value=fake_stat):
                    with self.assertRaises(a.DetectorError):
                        a.HerdrClient(path).call('pane.list', {}, 'pane_list')

    def test_port_boundaries_and_ipv6_wildcard(self):
        a = load_agent()
        for port in (0, 1, 1023, 65536):
            self.assertEqual(a.parse_tcp(tcp_row(port=port), 4, os.getuid()), {})
        for port in (1024, 65535):
            self.assertEqual(a.parse_tcp(tcp_row(port=port), 4, os.getuid()), {'123': ('127.0.0.1', port)})
        self.assertEqual(a.parse_tcp(tcp_row('0'*32), 6, os.getuid()), {})
        with self.assertRaises((ValueError, IndexError)):
            a.parse_tcp('not a tcp row', 4, os.getuid())

    def test_cli_failure_is_error_not_empty_snapshot(self):
        result = subprocess.run([sys.executable, str(AGENT), '--once'], env={**os.environ, 'HERDR_SOCKET_PATH': '/nonexistent/herdr-bridge-test.sock'}, capture_output=True, text=True, timeout=5)
        self.assertEqual(result.returncode, 1)
        frame = json.loads(result.stdout)
        self.assertEqual(frame['type'], 'error')
        self.assertNotIn('services', frame)
        self.assertEqual(frame['version'], 1)
        self.assertEqual(result.stderr, '')

    def test_frame_limits_and_diagnostic_controls(self):
        a = load_agent()
        self.assertTrue(hasattr(a, 'encode_frame'), 'frame bounds are missing')
        self.assertTrue(hasattr(a, 'error_frame'), 'error frame is missing')
        self.assertEqual(a.label('a\x00\x1b\n\u202eb'), 'ab')
        self.assertEqual(len(a.label('x'*200)), 128)
        frame = a.error_frame(a.DetectorError('bad\n\x1b\u202e' + 'x'*1000))
        self.assertLessEqual(len(frame['message']), 256)
        self.assertNotIn('\n', frame['message'])
        with self.assertRaises(a.DetectorError):
            a.encode_frame({'message': '😀'*20000})
        with self.assertRaises(a.DetectorError):
            a.encode_frame({'services': [{}]*129})

    def test_stable_ids_across_pid_changes_and_duplicate_endpoints(self):
        a = load_agent()
        api = FixtureAPI(os.getpid())
        with mock.patch.object(a.ProcTree, 'endpoints', return_value={('127.0.0.1', 5173)}):
            first = a.detect(api)
            api.pid += 1
            self.assertEqual(a.detect(api), first)
            def multi_call(method, params, expected):
                if method == 'pane.list':
                    return {'panes': [{'pane_id': 'w2:p1'}, {'pane_id': 'w1:p1'}]}
                return {'process_info': {'pane_id': params['pane_id'], 'foreground_processes': []}}
            api.call = multi_call
            snapshot = a.detect(api)
            self.assertEqual(len(snapshot['services']), 1)
            self.assertEqual(snapshot['services'][0]['pane'], 'w1:p1')
            self.assertEqual(snapshot['services'][0]['id'], first['services'][0]['id'])
        with mock.patch.object(a.ProcTree, 'endpoints', return_value={('127.0.0.1', p) for p in range(1024, 1152)}):
            frame = a.detect(FixtureAPI(os.getpid()))
            self.assertEqual(len(frame['services']), 128)
            self.assertLessEqual(len(a.encode_frame(frame)), 65536)

    def test_schema_failures_and_service_cap(self):
        a = load_agent()
        for bad in [None, {}, {'pane_id': 'wrong'}, {'pane_id': 'w1:p1', 'foreground_processes': None}, {'pane_id': 'w1:p1', 'foreground_processes': [{'pid': True}]}]:
            api = FixtureAPI(os.getpid())
            original = api.call
            api.call = lambda method, params, expected, bad=bad: original(method, params, expected) if method == 'pane.list' else {'process_info': bad}
            with self.assertRaises(a.DetectorError):
                a.detect(api)
        with mock.patch.object(a.ProcTree, 'endpoints', return_value={('127.0.0.1', p) for p in range(1024, 1153)}):
            with self.assertRaises(a.DetectorError):
                a.detect(FixtureAPI(os.getpid()))

    def test_loopback_listeners_only(self):
        self.assertTrue(AGENT.exists(), 'executable agent is not implemented')
        a = load_agent()
        rows = ''.join([
            tcp_row(), tcp_row('00000000', inode=124),
            tcp_row('0100007F', port=80, inode=125),
            tcp_row(state='01', inode=126), tcp_row(uid=os.getuid()+1, inode=127),
            tcp_row('0100000A', inode=128), tcp_row(port=0, inode=129),
        ])
        self.assertEqual(a.parse_tcp(rows, 4, os.getuid()), {'123': ('127.0.0.1', 5173)})
        self.assertEqual(a.parse_tcp(tcp_row('00000000000000000000000001000000'), 6, os.getuid()), {'123': ('::1', 5173)})


if __name__ == '__main__':
    unittest.main()
