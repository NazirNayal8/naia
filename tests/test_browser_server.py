"""Automatic ports bind atomically; explicit ports remain exact for SSH tunnels."""
import argparse
from contextlib import redirect_stderr, redirect_stdout
import errno
from http.server import BaseHTTPRequestHandler
import io
from pathlib import Path
import sys
import unittest
from unittest.mock import Mock, call, patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from naia.browser_server import PORT_POOL, bind_loopback, port_number
from naia.cli import parser
from naia.ui import serve


class BrowserServerTest(unittest.TestCase):
    def test_default_pool_is_bounded(self):
        self.assertEqual(list(PORT_POOL), list(range(8760, 8860)))

    def test_auto_port_uses_shuffled_candidates(self):
        server = Mock()
        with patch("naia.browser_server.PORT_POOL", [8760, 8761, 8762]), \
                patch("naia.browser_server.secrets.SystemRandom") as random, \
                patch("naia.browser_server.ThreadingHTTPServer", return_value=server) as construct:
            random.return_value.shuffle.side_effect = lambda ports: ports.reverse()
            self.assertIs(bind_loopback(BaseHTTPRequestHandler), server)
        random.return_value.shuffle.assert_called_once()
        construct.assert_called_once_with(("127.0.0.1", 8762), BaseHTTPRequestHandler)

    def test_collision_retries_next_candidate_without_preflight(self):
        server = Mock()
        with patch("naia.browser_server.PORT_POOL", [8760, 8761, 8762]), \
                patch("naia.browser_server.secrets.SystemRandom"), \
                patch("naia.browser_server.ThreadingHTTPServer", side_effect=[
                    OSError(errno.EADDRINUSE, "occupied"), server]) as construct:
            self.assertIs(bind_loopback(BaseHTTPRequestHandler), server)
        self.assertEqual(construct.call_args_list, [
            call(("127.0.0.1", 8760), BaseHTTPRequestHandler),
            call(("127.0.0.1", 8761), BaseHTTPRequestHandler),
        ])

    def test_exhausted_pool_falls_back_to_os_selected_port(self):
        server = Mock()
        with patch("naia.browser_server.PORT_POOL", [8760, 8761]), \
                patch("naia.browser_server.secrets.SystemRandom"), \
                patch("naia.browser_server.ThreadingHTTPServer", side_effect=[
                    OSError(errno.EADDRINUSE, "occupied"),
                    OSError(errno.EADDRINUSE, "occupied"), server]) as construct:
            self.assertIs(bind_loopback(BaseHTTPRequestHandler), server)
        self.assertEqual([entry.args[0] for entry in construct.call_args_list],
                         [("127.0.0.1", 8760), ("127.0.0.1", 8761), ("127.0.0.1", 0)])

    def test_explicit_port_including_zero_is_exact(self):
        for port in (0, 8767, 65535):
            with self.subTest(port=port), \
                    patch("naia.browser_server.secrets.SystemRandom") as random, \
                    patch("naia.browser_server.ThreadingHTTPServer") as construct:
                self.assertIs(bind_loopback(BaseHTTPRequestHandler, port), construct.return_value)
                construct.assert_called_once_with(("127.0.0.1", port), BaseHTTPRequestHandler)
                random.assert_not_called()

    def test_explicit_occupied_port_does_not_silently_move_tunnel(self):
        failure = OSError(errno.EADDRINUSE, "occupied")
        with patch("naia.browser_server.ThreadingHTTPServer", side_effect=failure) as construct:
            with self.assertRaises(OSError) as error:
                bind_loopback(BaseHTTPRequestHandler, 8767)
        self.assertIs(error.exception, failure)
        construct.assert_called_once_with(("127.0.0.1", 8767), BaseHTTPRequestHandler)

    def test_other_binding_errors_are_not_treated_as_collisions(self):
        for code in (errno.EACCES, errno.EADDRNOTAVAIL, errno.EIO):
            with self.subTest(errno=code), \
                    patch("naia.browser_server.PORT_POOL", [8760, 8761]), \
                    patch("naia.browser_server.secrets.SystemRandom"), \
                    patch("naia.browser_server.ThreadingHTTPServer",
                          side_effect=OSError(code, "binding failure")) as construct:
                with self.assertRaises(OSError) as error:
                    bind_loopback(BaseHTTPRequestHandler)
                self.assertEqual(error.exception.errno, code)
                self.assertEqual(construct.call_count, 1)

    def test_only_loopback_hosts_are_accepted(self):
        for host in ("0.0.0.0", "::", "cluster.example", "192.0.2.1"):
            with self.subTest(host=host), \
                    patch("naia.browser_server.ThreadingHTTPServer") as construct:
                with self.assertRaisesRegex(ValueError, "loopback only"):
                    bind_loopback(BaseHTTPRequestHandler, 8767, host=host)
                construct.assert_not_called()
        with patch("naia.browser_server.ThreadingHTTPServer") as construct:
            bind_loopback(BaseHTTPRequestHandler, 8767, host="localhost")
        construct.assert_called_once_with(("localhost", 8767), BaseHTTPRequestHandler)

    def test_invalid_explicit_ports_do_not_attempt_binding(self):
        for port in (True, False, -1, 65536, "8767", 1.5):
            with self.subTest(port=port), \
                    patch("naia.browser_server.ThreadingHTTPServer") as construct:
                with self.assertRaisesRegex(ValueError, "0 to 65535"):
                    bind_loopback(BaseHTTPRequestHandler, port)
                construct.assert_not_called()

    def test_port_number_validates_integer_range(self):
        for value, expected in (("0", 0), ("8767", 8767), ("65535", 65535)):
            with self.subTest(value=value):
                self.assertEqual(port_number(value), expected)
        for value in (None, "", "auto", "1.5", "-1", "65536"):
            with self.subTest(value=value):
                with self.assertRaises(argparse.ArgumentTypeError):
                    port_number(value)

    def test_ui_cli_uses_automatic_port_unless_explicit(self):
        command = parser()
        self.assertIsNone(command.parse_args(["ui"]).port)
        self.assertEqual(command.parse_args(["ui", "--port", "0"]).port, 0)
        self.assertEqual(command.parse_args(["ui", "--port", "8767"]).port, 8767)

    def test_ui_cli_rejects_invalid_port_before_dispatch(self):
        for value in ("-1", "65536", "1.5", "auto"):
            with self.subTest(value=value), redirect_stderr(io.StringIO()) as stderr:
                with self.assertRaises(SystemExit) as error:
                    parser().parse_args(["ui", "--port", value])
                self.assertEqual(error.exception.code, 2)
                self.assertIn("Port must be an integer from 0 to 65535", stderr.getvalue())

    def test_two_simultaneous_auto_servers_handle_identical_candidate_order(self):
        with patch("naia.browser_server.secrets.SystemRandom") as random:
            first = bind_loopback(BaseHTTPRequestHandler)
            self.addCleanup(first.server_close)
            second = bind_loopback(BaseHTTPRequestHandler)
            self.addCleanup(second.server_close)
        self.assertNotEqual(first.server_port, second.server_port)
        self.assertEqual(first.server_address[0], "127.0.0.1")
        self.assertEqual(second.server_address[0], "127.0.0.1")
        self.assertEqual(random.return_value.shuffle.call_count, 2)

    def test_ui_prints_actual_bound_port_and_closes_after_interrupt(self):
        project, request_handler, server = Mock(), Mock(), Mock(server_port=48231)
        server.serve_forever.side_effect = KeyboardInterrupt
        stdout = io.StringIO()
        with patch("naia.ui.handler", return_value=request_handler) as make_handler, \
                patch("naia.ui.bind_loopback", return_value=server) as bind, \
                redirect_stdout(stdout):
            serve(project, reports_root="reports")
        self.assertEqual(stdout.getvalue(), "NAIA: http://127.0.0.1:48231\n")
        bind.assert_called_once_with(request_handler, None)
        self.assertEqual(make_handler.call_args.kwargs, {"reports_root": "reports"})
        server.serve_forever.assert_called_once_with()
        server.server_close.assert_called_once_with()

    def test_ui_closes_server_when_serving_raises(self):
        server = Mock(server_port=8767)
        server.serve_forever.side_effect = RuntimeError("test serving failure")
        with patch("naia.ui.handler"), patch("naia.ui.bind_loopback", return_value=server) as bind, \
                redirect_stdout(io.StringIO()):
            with self.assertRaisesRegex(RuntimeError, "test serving failure"):
                serve(Mock(), 8767)
        self.assertEqual(bind.call_args.args[1], 8767)
        server.server_close.assert_called_once_with()


if __name__ == "__main__":
    unittest.main()
