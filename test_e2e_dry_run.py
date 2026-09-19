import hashlib, hmac, json, os, subprocess, tempfile, threading, time, unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.request import Request, urlopen
from urllib.error import HTTPError

SECRET = "e2e-secret"

class CallbackHandler(BaseHTTPRequestHandler):
    received = []
    def do_POST(self):
        n = int(self.headers.get("Content-Length", "0"))
        raw = self.rfile.read(n)
        CallbackHandler.received.append((dict(self.headers), raw))
        self.send_response(200); self.end_headers(); self.wfile.write(b'{"ok":true}')
    def log_message(self, *args): return

def sign(ts, raw):
    return hmac.new(SECRET.encode(), f"{ts}.".encode() + raw, hashlib.sha256).hexdigest()

class BrokerE2E(unittest.TestCase):
    def test_dry_run_e2e_security_and_idempotency(self):
        callback = ThreadingHTTPServer(("127.0.0.1", 0), CallbackHandler)
        threading.Thread(target=callback.serve_forever, daemon=True).start()
        with tempfile.TemporaryDirectory() as td:
            port = 18991
            env = os.environ.copy()
            env.update({
                "ALI100_SHARED_SECRET": SECRET,
                "ALI100_MODE": "DRY_RUN",
                "ALI100_LEDGER_DB": os.path.join(td, "ledger.sqlite3"),
                "ALI100_CALLBACK_URL": f"http://127.0.0.1:{callback.server_port}/callback",
                "PORT": str(port),
            })
            p = subprocess.Popen(["python", "broker_service.py"], env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
            try:
                for _ in range(30):
                    try:
                        urlopen(f"http://127.0.0.1:{port}/health", timeout=0.5); break
                    except Exception: time.sleep(0.1)

                body = {
                    "request_id": "e2e-request-1",
                    "idempotency_key": "e2e-idem-1",
                    "deal_id": "deal-e2e-1",
                    "amount": 100000,
                    "approved_by_owner": True,
                    "adapter": "webhook"
                }
                raw = json.dumps(body, separators=(",", ":")).encode()
                ts = str(int(time.time()))
                req = Request(f"http://127.0.0.1:{port}/v1/executions", data=raw, headers={
                    "Content-Type":"application/json","X-ALI100-Timestamp":ts,"X-ALI100-Signature":sign(ts,raw)
                }, method="POST")
                first = json.loads(urlopen(req, timeout=3).read())
                self.assertTrue(first["ok"])
                self.assertEqual(first["status"], "COMPLETED")
                self.assertFalse(first["result"]["external_effect"])
                self.assertEqual(first["result"]["receipt"], "DRY_RUN")

                req2 = Request(f"http://127.0.0.1:{port}/v1/executions", data=raw, headers={
                    "Content-Type":"application/json","X-ALI100-Timestamp":str(int(time.time())),
                    "X-ALI100-Signature":sign(str(int(time.time())),raw)
                }, method="POST")
                second = json.loads(urlopen(req2, timeout=3).read())
                self.assertTrue(second["idempotent"])

                bad = Request(f"http://127.0.0.1:{port}/v1/executions", data=raw, headers={
                    "Content-Type":"application/json","X-ALI100-Timestamp":str(int(time.time())),
                    "X-ALI100-Signature":"0"*64
                }, method="POST")
                with self.assertRaises(HTTPError) as cm: urlopen(bad, timeout=3)
                self.assertEqual(cm.exception.code, 401)

                replay_ts = str(int(time.time()) - 301)
                replay = Request(f"http://127.0.0.1:{port}/v1/executions", data=raw, headers={
                    "Content-Type":"application/json","X-ALI100-Timestamp":replay_ts,
                    "X-ALI100-Signature":sign(replay_ts,raw)
                }, method="POST")
                with self.assertRaises(HTTPError) as cm: urlopen(replay, timeout=3)
                self.assertEqual(cm.exception.code, 401)

                self.assertTrue(CallbackHandler.received)
                headers, callback_raw = CallbackHandler.received[-1]
                self.assertEqual(headers["X-ali100-timestamp"], headers["X-ali100-timestamp"])
                self.assertEqual(headers["X-ali100-signature"], sign(headers["X-ali100-timestamp"], callback_raw))
                callback_body = json.loads(callback_raw)
                self.assertEqual(callback_body["mode"], "DRY_RUN")
                self.assertFalse(callback_body["result"]["external_effect"])

                import sqlite3
                db = sqlite3.connect(env["ALI100_LEDGER_DB"])
                events = [r[0] for r in db.execute("SELECT event FROM ledger ORDER BY id")]
                self.assertEqual(events, ["REQUEST_ACCEPTED", "ADAPTER_RESULT"])
            finally:
                p.terminate(); p.wait(timeout=5)
                callback.shutdown()

if __name__ == "__main__":
    unittest.main()
