import hashlib,hmac,json,os,tempfile,unittest,urllib.request
os.environ["ALI100_SHARED_SECRET"]="test-secret"
os.environ["ALI100_LEDGER_DB"]=os.path.join(tempfile.gettempdir(),"ali100-broker-test.sqlite3")
os.environ["ALI100_MODE"]="DRY_RUN"
from broker_service import execute

class BrokerTests(unittest.TestCase):
    def test_dry_run_is_idempotent(self):
        body={"request_id":"r1","idempotency_key":"k1","deal_id":"d1","amount":1000,"adapter":"webhook"}
        a=execute(body); b=execute(body)
        self.assertTrue(a["ok"]); self.assertTrue(b["idempotent"]); self.assertEqual(a["request_id"],b["request_id"])
    def test_live_ready_blocks_execution(self):
        os.environ["ALI100_MODE"]="LIVE_READY"
        import broker_service; broker_service.MODE="LIVE_READY"
        with self.assertRaises(PermissionError): execute({"request_id":"r2","idempotency_key":"k2","deal_id":"d2","amount":1000})
if __name__=="__main__": unittest.main()
