"""Host and same-origin policy for local and trusted LAN/VPN deployments."""
import unittest
from contextlib import redirect_stderr, redirect_stdout
import io
from unittest.mock import Mock, patch

from app.server import check_host, check_origin, serve_native


class ServerAccessTests(unittest.TestCase):
    def test_server_addresses_and_names_need_no_configuration(self):
        for host in ('192.168.1.10:8080', 'another-server.local:9090', '[fd00::10]:8080', 'localhost:8080'):
            with self.subTest(host=host):
                check_host(host)

    def test_writes_require_the_same_origin(self):
        check_origin('http://192.168.1.10:8080', '192.168.1.10:8080')
        check_origin('http://kicaddiff.local:8080', 'kicaddiff.local:8080')
        for origin in ('https://attacker.example', 'http://192.168.1.10:9090', 'http://kicaddiff.local:8080'):
            with self.subTest(origin=origin), self.assertRaises(ValueError):
                check_origin(origin, '192.168.1.10:8080')

    def test_malformed_host_headers_cannot_bypass_the_policy(self):
        for host in ('user@localhost:8080', 'localhost/path', 'localhost?query',
                     'localhost#fragment', 'localhost:invalid', 'localhost:99999',
                     ' localhost:8080', 'localhost:8080 ', 'localhost,attacker.example'):
            with self.subTest(host=host), self.assertRaises(ValueError):
                check_host(host)

    def test_native_http_handler_enforces_lan_host_and_origin_policy(self):
        responses = {}
        application = Mock()
        application.dispatch.return_value = {'ok': True}
        server = Mock()

        class Connection:
            def __init__(self, request):
                self.request = request
                self.response = bytearray()

            def makefile(self, *args):
                return io.BytesIO(self.request)

            def sendall(self, data):
                self.response.extend(data)

        def listener(address, handler):
            def requests():
                for name, method, host, origin in (
                    ('lan_read', 'GET', 'kicaddiff.local:8080', None),
                    ('lan_write', 'POST', 'kicaddiff.local:8080', 'http://kicaddiff.local:8080'),
                    ('other_server_name', 'GET', 'another-server.local:8080', None),
                    ('foreign_origin', 'POST', 'kicaddiff.local:8080', 'https://attacker.example'),
                ):
                    headers = [f'{method} /api/repos HTTP/1.1', f'Host: {host}',
                               'Content-Type: application/json', 'Content-Length: 2']
                    if origin:
                        headers.append('Origin: '+origin)
                    connection = Connection(('\r\n'.join(headers)+'\r\n\r\n{}').encode())
                    handler(connection, ('192.168.1.20', 32100), server)
                    responses[name] = int(bytes(connection.response).split(b' ', 2)[1])
            server.serve_forever.side_effect = requests
            return server

        with patch('app.server.ThreadingHTTPServer', side_effect=listener), redirect_stderr(io.StringIO()), redirect_stdout(io.StringIO()):
            serve_native(application, '0.0.0.0', 8080)
        self.assertEqual(responses, {'lan_read': 200, 'lan_write': 200,
                                     'other_server_name': 200, 'foreign_origin': 400})
        self.assertEqual(application.dispatch.call_count, 3)
        application.close.assert_called_once()
