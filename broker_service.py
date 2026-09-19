#!/usr/bin/env python3
import hashlib, hmac, json, os, sqlite3, time, uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.request import Request, urlopen
from urllib.error import URLError, HTTPError

DB_PATH=os.getenv("ALI100_LEDGER_DB","./ali100_ledger.sqlite3")
MODE=os.getenv("ALI100_MODE","DRY_RUN").upper()
SHARED_SECRET=os.getenv("ALI100_SHARED_SECRET","")
CALLBACK_URL=os.getenv("ALI100_CALLBACK_URL","")
ADAPTER_WEBHOOK_URL=os.getenv("ALI100_ADAPTER_WEBHOOK_URL","")
REPLAY_WINDOW=int(os.getenv("ALI100_REPLAY_WINDOW_SEC","300"))
MAX_AMOUNT=int(os.getenv("ALI100_MAX_AMOUNT","100000000"))

def db():
    c=sqlite3.connect(DB_PATH)
    c.execute("""CREATE TABLE IF NOT EXISTS executions(
      request_id TEXT PRIMARY KEY, idempotency_key TEXT UNIQUE NOT NULL,
      deal_id TEXT NOT NULL, mode TEXT NOT NULL, status TEXT NOT NULL,
      request_json TEXT NOT NULL, response_json TEXT, created_at INTEGER NOT NULL,
      updated_at INTEGER NOT NULL)""")
    c.execute("""CREATE TABLE IF NOT EXISTS ledger(
      id INTEGER PRIMARY KEY AUTOINCREMENT, request_id TEXT NOT NULL,
      event TEXT NOT NULL, payload_json TEXT NOT NULL, created_at INTEGER NOT NULL)""")
    c.commit()
    return c

def canonical(body):
    return json.dumps(body,ensure_ascii=False,separators=(",",":"),sort_keys=True).encode()

def signature(ts,raw):
    return hmac.new(SHARED_SECRET.encode(),f"{ts}.".encode()+raw,hashlib.sha256).hexdigest()

def verify_signature(ts,sig,raw):
    if not SHARED_SECRET or not ts or not sig: return False
    try: t=int(ts)
    except ValueError: return False
    if abs(int(time.time())-t)>REPLAY_WINDOW: return False
    return hmac.compare_digest(signature(t,raw),sig)

def ledger(c,request_id,event,payload):
    now=int(time.time())
    c.execute("INSERT INTO ledger(request_id,event,payload_json,created_at) VALUES(?,?,?,?)",
              (request_id,event,json.dumps(payload,ensure_ascii=False),now))
    c.commit()

def callback(payload):
    if not CALLBACK_URL: return {"sent":False,"reason":"CALLBACK_URL_NOT_CONFIGURED"}
    raw=json.dumps(payload,ensure_ascii=False,separators=(",",":")).encode()
    try:
        r=urlopen(Request(CALLBACK_URL,data=raw,headers={"Content-Type":"application/json"},method="POST"),timeout=15)
        return {"sent":True,"status":r.status}
    except Exception as e:
        return {"sent":False,"reason":str(e)[:300]}

def adapter(request_body):
    adapter_name=request_body.get("adapter","webhook")
    if MODE=="DRY_RUN":
        return {"executed":False,"adapter":adapter_name,"receipt":"DRY_RUN","external_effect":False}
    if adapter_name!="webhook":
        raise ValueError("Unsupported adapter")
    if not ADAPTER_WEBHOOK_URL:
        raise RuntimeError("ALI100_ADAPTER_WEBHOOK_URL is not configured")
    raw=json.dumps(request_body,ensure_ascii=False,separators=(",",":")).encode()
    r=urlopen(Request(ADAPTER_WEBHOOK_URL,data=raw,headers={"Content-Type":"application/json"},method="POST"),timeout=30)
    text=r.read(4000).decode("utf-8","replace")
    try: response=json.loads(text)
    except Exception: response={"raw":text}
    return {"executed":True,"adapter":adapter_name,"external_effect":True,"upstream_status":r.status,"receipt":response}

def execute(body):
    rid=str(body.get("request_id","")).strip()
    idem=str(body.get("idempotency_key",rid)).strip()
    deal=str(body.get("deal_id","")).strip()
    if not rid or not deal or not idem: raise ValueError("request_id, deal_id and idempotency_key are required")
    amount=body.get("amount")
    if not isinstance(amount,int) or amount<0 or amount>MAX_AMOUNT: raise ValueError("amount must be a non-negative integer within risk limit")
    if MODE=="LIVE" and body.get("approved_by_owner") is not True: raise PermissionError("LIVE execution requires owner approval")
    if MODE=="LIVE_READY": raise PermissionError("LIVE_READY is validation-only; explicit LIVE mode is required")
    c=db()
    prior=c.execute("SELECT request_id,status,response_json FROM executions WHERE idempotency_key=?",(idem,)).fetchone()
    if prior:
        return {"ok":True,"idempotent":True,"request_id":prior[0],"status":prior[1],"response":json.loads(prior[2]) if prior[2] else None}
    now=int(time.time())
    c.execute("INSERT INTO executions(request_id,idempotency_key,deal_id,mode,status,request_json,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?)",
              (rid,idem,deal,MODE,"RISK_PENDING",json.dumps(body,ensure_ascii=False),now,now))
    c.commit(); ledger(c,rid,"REQUEST_ACCEPTED",{"mode":MODE,"deal_id":deal})
    try:
        result=adapter(body)
        status="COMPLETED" if result.get("executed") or MODE=="DRY_RUN" else "SUBMITTED"
        ledger(c,rid,"ADAPTER_RESULT",result)
    except Exception as e:
        result={"executed":False,"external_effect":False,"error":str(e)[:500]}
        status="FAILED"; ledger(c,rid,"ADAPTER_FAILED",result)
    c.execute("UPDATE executions SET status=?,response_json=?,updated_at=? WHERE request_id=?",
              (status,json.dumps(result,ensure_ascii=False),int(time.time()),rid)); c.commit()
    cb=callback({"event":"execution.completed","request_id":rid,"deal_id":deal,"status":status,"mode":MODE,"result":result})
    return {"ok":status=="COMPLETED","request_id":rid,"status":status,"mode":MODE,"result":result,"callback":cb}

class Handler(BaseHTTPRequestHandler):
    def send_json(self,code,payload):
        raw=json.dumps(payload,ensure_ascii=False).encode()
        self.send_response(code); self.send_header("Content-Type","application/json"); self.send_header("Content-Length",str(len(raw))); self.end_headers(); self.wfile.write(raw)
    def do_GET(self):
        if self.path=="/health":
            self.send_json(200,{"ok":True,"service":"ALI100-Broker","mode":MODE,"external_execution_enabled":bool(ADAPTER_WEBHOOK_URL and MODE=="LIVE")})
        else: self.send_json(404,{"error":"not_found"})
    def do_POST(self):
        if self.path!="/v1/executions": self.send_json(404,{"error":"not_found"}); return
        n=int(self.headers.get("Content-Length","0"))
        raw=self.rfile.read(n)
        if not verify_signature(self.headers.get("X-ALI100-Timestamp",""),self.headers.get("X-ALI100-Signature",""),raw):
            self.send_json(401,{"ok":False,"error":"invalid_signature"}); return
        try:
            body=json.loads(raw)
            result=execute(body)
            self.send_json(200 if result["ok"] else 409,result)
        except PermissionError as e: self.send_json(403,{"ok":False,"error":str(e)})
        except (ValueError,json.JSONDecodeError) as e: self.send_json(400,{"ok":False,"error":str(e)})
        except Exception as e: self.send_json(500,{"ok":False,"error":str(e)[:500]})
    def log_message(self,*args): return

if __name__=="__main__":
    port=int(os.getenv("PORT","8080"))
    if not SHARED_SECRET: print("WARNING: ALI100_SHARED_SECRET is not configured")
    ThreadingHTTPServer(("0.0.0.0",port),Handler).serve_forever()
