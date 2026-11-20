import http.client
import os
import threading
import unittest
from http.server import ThreadingHTTPServer

os.environ.setdefault("ALI100_SHARED_SECRET", "test-secret")
os.environ.setdefault("ALI100_MODE", "DRY_RUN")
import broker_service as service


class RequestBoundsTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.original_limit = service.MAX_BODY_BYTES
        service.MAX_BODY_BYTES = 8
        cls.server = ThreadingHTTPServer(("127.0.0.1", 0), service.Handler)
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()
        cls.thread.join(timeout=2)
        service.MAX_BODY_BYTES = cls.original_limit

    def test_rejects_oversized_body_before_reading_payload(self):
        conn = http.client.HTTPConnection("127.0.0.1", self.server.server_port, timeout=3)
        conn.putrequest("POST", "/v1/executions")
        conn.putheader("Content-Length", "9")
        conn.endheaders()
        response = conn.getresponse()
        self.assertEqual(response.status, 413)
        self.assertEqual(response.read(), b'{"ok": false, "error": "request_body_too_large"}')
        conn.close()


if __name__ == "__main__":
    unittest.main()
