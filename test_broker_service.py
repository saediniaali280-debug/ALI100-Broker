import json,os,tempfile,unittest
import broker_service

class BrokerTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        broker_service.DB_PATH = os.path.join(self.temp.name, "ledger.sqlite3")
        broker_service.MODE = "DRY_RUN"
        broker_service.SHARED_SECRET = "test-secret"
        broker_service.CALLBACK_URL = ""
        broker_service.ADAPTER_WEBHOOK_URL = ""

    def tearDown(self):
        self.temp.cleanup()

    def test_dry_run_is_idempotent(self):
        body={"request_id":"r1","idempotency_key":"k1","deal_id":"d1","amount":1000,"adapter":"webhook"}
        a=broker_service.execute(body)
        b=broker_service.execute(body)
        self.assertTrue(a["ok"])
        self.assertTrue(b["idempotent"])
        self.assertTrue(b["ok"])
        self.assertEqual(a["request_id"],b["request_id"])

    def test_live_ready_blocks_execution(self):
        broker_service.MODE = "LIVE_READY"
        with self.assertRaises(PermissionError):
            broker_service.execute({"request_id":"r2","idempotency_key":"k2","deal_id":"d2","amount":1000})

    def test_failed_retry_does_not_report_success(self):
        broker_service.MODE = "LIVE"
        body={"request_id":"r3","idempotency_key":"k3","deal_id":"d3","amount":1000,"adapter":"webhook","approved_by_owner":True}
        first=broker_service.execute(body)
        second=broker_service.execute(body)
        self.assertFalse(first["ok"])
        self.assertEqual(first["status"],"FAILED")
        self.assertFalse(second["ok"])
        self.assertEqual(second["status"],"FAILED")

    def test_reusing_idempotency_key_for_different_payload_is_rejected(self):
        first={"request_id":"r4","idempotency_key":"k4","deal_id":"d4","amount":1000,"adapter":"webhook"}
        second={"request_id":"r5","idempotency_key":"k4","deal_id":"d5","amount":2000,"adapter":"webhook"}
        self.assertTrue(broker_service.execute(first)["ok"])
        result=broker_service.execute(second)
        self.assertFalse(result["ok"])
        self.assertEqual(result["error"],"idempotency_key_conflict")
        self.assertEqual(result["request_id"],"r4")

if __name__=="__main__": unittest.main()
