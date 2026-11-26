import os
import sys
import json
import logging
import threading
import uuid
import hmac
import signal
import argparse
import tempfile
from http.server import ThreadingHTTPServer, BaseHTTPRequestHandler
from datetime import datetime, timezone

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
_write_lock = threading.Lock()
TOKEN_VALID = False

def load_environment():
    """Lädt .env-Dateien fehlertolerant, bereinigt CRLF, Whitespaces und Quotes."""
    base_dir = os.path.dirname(os.path.abspath(__file__))
    project_dir = os.path.dirname(base_dir)
    env_paths = [
        os.path.join(base_dir, ".env"),
        os.path.join(project_dir, "RSI Bot", ".env")
    ]
    
    for path in env_paths:
        if os.path.isfile(path):
            with open(path, 'r', encoding='utf-8') as f:
                for line in f:
                    line = line.strip(' \r\n')
                    if not line or line.startswith('#'):
                        continue
                    if '=' in line:
                        k, v = line.split('=', 1)
                        k = k.strip()
                        v = v.strip().strip("'\"")
                        if k not in os.environ:
                            os.environ[k] = v

class TelemetryHTTPServer(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = True

class TelemetryRequestHandler(BaseHTTPRequestHandler):
    
    def log_message(self, format, *args):
        # Unterdrückt sensible Daten im Log (Standard-Log zeigt nur Request-Line)
        logging.info("%s - %s", self.client_address[0], format % args)

    def send_json(self, status, payload, extra_headers=None):
        self.send_response(status)
        self.send_header('Content-Type', 'application/json')
        if extra_headers:
            for k, v in extra_headers.items():
                self.send_header(k, v)
        self.end_headers()
        self.wfile.write(json.dumps(payload).encode('utf-8'))

    def do_GET(self):
        if self.path == '/health':
            self.send_json(200, {
                "status": "ok",
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "token_configured": TOKEN_VALID
            })
        else:
            self.send_json(404, {"error": "Not Found"})

    def do_POST(self):
        if self.path not in ('/api/telemetry/fleet', '/api/telemetry/journal'):
            return self.send_json(404, {"error": "Not Found"})

        # Stufe 1: Server-Token bereit
        if not TOKEN_VALID:
            return self.send_json(503, {"error": "Service Unavailable - Server Token missing or invalid"})

        # Stufe 2: Bearer-Auth
        auth_header = self.headers.get('Authorization', '')
        if not auth_header.lower().startswith('bearer '):
            return self.send_json(401, {"error": "Unauthorized"}, {'WWW-Authenticate': 'Bearer'})
        
        token = auth_header[7:].strip()
        secret = os.environ.get("TELEMETRY_SECRET_TOKEN", "")
        if not hmac.compare_digest(token, secret):
            return self.send_json(401, {"error": "Unauthorized"}, {'WWW-Authenticate': 'Bearer'})

        # Stufe 3: Content-Type
        if 'application/json' not in self.headers.get('Content-Type', ''):
            return self.send_json(415, {"error": "Unsupported Media Type - Must be application/json"})

        # Stufe 4: Payload-Größenlimit (64 KB für Fleet, 2 MB für Journal)
        clength_str = self.headers.get('Content-Length')
        if not clength_str:
            return self.send_json(411, {"error": "Length Required"})
        try:
            clength = int(clength_str)
            if clength <= 0:
                raise ValueError()
        except ValueError:
            return self.send_json(400, {"error": "Bad Request - Invalid Content-Length"})
        
        max_bytes = 2097152 if self.path == '/api/telemetry/journal' else 65536
        if clength > max_bytes:
            limit_label = "2MB" if self.path == '/api/telemetry/journal' else "64KB"
            return self.send_json(413, {"error": f"Payload Too Large - Exceeds {limit_label}"})

        raw_data = self.rfile.read(clength)

        # Stufe 5: JSON-Syntax & Root-Dictionary
        try:
            payload = json.loads(raw_data.decode('utf-8'))
        except (json.JSONDecodeError, UnicodeDecodeError):
            return self.send_json(400, {"error": "Bad Request - Invalid JSON"})

        if not isinstance(payload, dict):
            return self.send_json(400, {"error": "Bad Request - JSON must be an object"})

        payload_keys = set(payload.keys())

        if self.path == '/api/telemetry/fleet':
            allowed_keys = {
                "schema_version", "updated_at", "accounts", "node_origin",
                "executor_mode", "kill_switch_active", "timestamp", "live_prices"
            }
            required_keys = {"schema_version", "updated_at", "accounts"}
            
            if not required_keys.issubset(payload_keys):
                return self.send_json(400, {"error": "Bad Request - Missing required keys"})
            if not payload_keys.issubset(allowed_keys):
                return self.send_json(400, {"error": "Bad Request - Unknown keys in payload"})

            # Stufe 6: Inhalts- & Zeitstempel-Plausibilität
            if type(payload["schema_version"]) is not int or payload["schema_version"] != 1:
                return self.send_json(400, {"error": "Bad Request - Invalid schema_version"})
            
            if "kill_switch_active" in payload and type(payload["kill_switch_active"]) is not bool:
                return self.send_json(400, {"error": "Bad Request - kill_switch_active must be bool"})

            accounts = payload["accounts"]
            if not isinstance(accounts, dict) or not accounts:
                return self.send_json(400, {"error": "Bad Request - accounts must be a non-empty object"})
            
            required_acc_keys = {"account_id", "currency", "equity", "daily_buffer", "max_dd_buffer"}
            for acc_k, acc_v in accounts.items():
                if not isinstance(acc_v, dict) or not required_acc_keys.issubset(set(acc_v.keys())):
                    return self.send_json(400, {"error": "Bad Request - invalid account structure"})

            if not isinstance(payload["updated_at"], str):
                return self.send_json(400, {"error": "Bad Request - Invalid ISO-8601 timestamp"})

            try:
                ts_str = payload["updated_at"].replace("Z", "+00:00")
                dt = datetime.fromisoformat(ts_str)
                if dt.tzinfo is None:
                    dt = dt.replace(tzinfo=timezone.utc)
                
                delta_sec = (datetime.now(timezone.utc) - dt).total_seconds()
                if delta_sec > 300 or delta_sec < -60:
                    return self.send_json(422, {"error": "Unprocessable Entity - Timestamp out of valid range"})
            except ValueError:
                return self.send_json(400, {"error": "Bad Request - Invalid ISO-8601 timestamp"})

            # Speicherung
            if not self.save_snapshot(payload):
                return self.send_json(500, {"error": "Internal Server Error during write"})

            self.send_json(200, {"status": "ok"})

        elif self.path == '/api/telemetry/journal':
            required_keys = {"schema_version", "updated_at", "csv_content"}
            allowed_keys = {"schema_version", "updated_at", "csv_content", "node_origin", "row_count"}

            if not required_keys.issubset(payload_keys):
                return self.send_json(400, {"error": "Bad Request - Missing required keys"})
            if not payload_keys.issubset(allowed_keys):
                return self.send_json(400, {"error": "Bad Request - Unknown keys in payload"})

            if type(payload["schema_version"]) is not int or payload["schema_version"] != 1:
                return self.send_json(400, {"error": "Bad Request - Invalid schema_version"})

            if not isinstance(payload["updated_at"], str):
                return self.send_json(400, {"error": "Bad Request - Invalid ISO-8601 timestamp"})

            try:
                ts_str = payload["updated_at"].replace("Z", "+00:00")
                dt = datetime.fromisoformat(ts_str)
                if dt.tzinfo is None:
                    dt = dt.replace(tzinfo=timezone.utc)

                delta_sec = (datetime.now(timezone.utc) - dt).total_seconds()
                if delta_sec > 300 or delta_sec < -60:
                    return self.send_json(422, {"error": "Unprocessable Entity - Timestamp out of valid range"})
            except ValueError:
                return self.send_json(400, {"error": "Bad Request - Invalid ISO-8601 timestamp"})

            csv_content = payload["csv_content"]
            if not isinstance(csv_content, str):
                return self.send_json(400, {"error": "Bad Request - csv_content must be a string"})

            if csv_content.strip():
                first_line = next((line for line in csv_content.splitlines() if line.strip()), "")
                header_cols = [col.strip().strip('"').strip("'").lstrip('\ufeff') for col in first_line.split(",")]
                if "id" not in header_cols or "status" not in header_cols:
                    return self.send_json(400, {"error": "Invalid CSV header"})

            if not self.save_journal(csv_content):
                return self.send_json(500, {"error": "Internal Server Error during write"})

            self.send_json(200, {"status": "ok"})

    def save_snapshot(self, payload):
        test_dir = os.environ.get("_TEST_TARGET_DIR")
        if test_dir:
            target_dir = test_dir
        else:
            base_dir = os.path.dirname(os.path.abspath(__file__))
            user = os.environ.get("TELEMETRY_TARGET_USER", "admin")
            target_dir = os.path.join(base_dir, "users", user)
            os.makedirs(target_dir, exist_ok=True)
            
        target_path = os.path.join(target_dir, "fleet_snapshot.json")
        tid = threading.get_native_id()
        uid = uuid.uuid4().hex
        tmp_path = os.path.join(target_dir, f"fleet_snapshot.{tid}.{uid}.tmp")

        with _write_lock:
            try:
                with open(tmp_path, 'w', encoding='utf-8') as f:
                    json.dump(payload, f, ensure_ascii=False)
                    f.flush()
                    os.fsync(f.fileno())
                os.replace(tmp_path, target_path)
                return True
            except Exception as e:
                logging.error(f"Error saving snapshot: {e}")
                return False
            finally:
                if os.path.exists(tmp_path):
                    try:
                        os.unlink(tmp_path)
                    except:
                        pass

    def save_journal(self, csv_content: str) -> bool:
        test_dir = os.environ.get("_TEST_TARGET_DIR")
        if test_dir:
            target_dir = test_dir
        else:
            base_dir = os.path.dirname(os.path.abspath(__file__))
            user = os.environ.get("TELEMETRY_TARGET_USER", "admin")
            target_dir = os.path.join(base_dir, "users", user)
            os.makedirs(target_dir, exist_ok=True)

        target_path = os.path.join(target_dir, "netcup_trade_journal.csv")
        tid = threading.get_native_id()
        uid = uuid.uuid4().hex
        tmp_path = os.path.join(target_dir, f"netcup_trade_journal.{tid}.{uid}.tmp")

        with _write_lock:
            try:
                with open(tmp_path, 'w', encoding='utf-8', newline='') as f:
                    f.write(csv_content)
                    f.flush()
                    os.fsync(f.fileno())
                os.replace(tmp_path, target_path)
                return True
            except Exception as e:
                logging.error(f"Error saving journal: {e}")
                return False
            finally:
                if os.path.exists(tmp_path):
                    try:
                        os.unlink(tmp_path)
                    except:
                        pass

    def do_PUT(self): self.send_json(405, {"error": "Method Not Allowed"})
    def do_DELETE(self): self.send_json(405, {"error": "Method Not Allowed"})
    def do_PATCH(self): self.send_json(405, {"error": "Method Not Allowed"})

def run_self_test():
    import http.client
    import time
    
    logging.info("Starting self-test...")
    with tempfile.TemporaryDirectory() as temp_dir:
        os.environ["TELEMETRY_BIND_HOST"] = "127.0.0.1"
        os.environ["TELEMETRY_BIND_PORT"] = "0"
        os.environ["_TEST_TARGET_DIR"] = temp_dir
        
        # Test 1: Fail Closed (Token missing)
        global TOKEN_VALID
        TOKEN_VALID = False
        
        server = TelemetryHTTPServer(("127.0.0.1", 0), TelemetryRequestHandler)
        port = server.server_address[1]
        t = threading.Thread(target=server.serve_forever)
        t.start()
        
        try:
            conn = http.client.HTTPConnection("127.0.0.1", port)
            valid_payload = json.dumps({
                "schema_version": 1,
                "updated_at": datetime.now(timezone.utc).isoformat(),
                "accounts": {"acc1": {"account_id": "a", "currency": "USD", "equity": 1, "daily_buffer": 1, "max_dd_buffer": 1}}
            })
            
            conn.request("POST", "/api/telemetry/fleet", valid_payload, {"Content-Type": "application/json", "Authorization": "Bearer VALIDTOKEN_12345678901234567890123"})
            r = conn.getresponse()
            assert r.status == 503, f"Fail-Closed test failed (got {r.status})"
            r.read()
            
            # Setup for rest of tests
            os.environ["TELEMETRY_SECRET_TOKEN"] = "VALIDTOKEN_12345678901234567890123"
            TOKEN_VALID = True
            
            # Test 2: Auth Reject
            conn.request("POST", "/api/telemetry/fleet", valid_payload, {"Content-Type": "application/json", "Authorization": "Bearer BAD"})
            r = conn.getresponse()
            assert r.status == 401, f"Auth test failed (got {r.status})"
            r.read()

            # Test 3: Size limit
            huge_payload = " " * 70000
            conn.request("POST", "/api/telemetry/fleet", huge_payload, {"Content-Type": "application/json", "Authorization": "Bearer VALIDTOKEN_12345678901234567890123"})
            r = conn.getresponse()
            assert r.status == 413, f"Size limit test failed (got {r.status})"
            r.read()

            # Test 4: Schema Whitelist
            bad_payload = json.dumps({"schema_version": 1, "updated_at": datetime.now(timezone.utc).isoformat(), "accounts": {}, "bad_key": True})
            conn.request("POST", "/api/telemetry/fleet", bad_payload, {"Content-Type": "application/json", "Authorization": "Bearer VALIDTOKEN_12345678901234567890123"})
            r = conn.getresponse()
            assert r.status == 400, f"Whitelist test failed (got {r.status})"
            r.read()

            # Test 5: Replay / Timestamp
            old_ts = (datetime.now(timezone.utc).timestamp() - 600)
            old_payload = json.dumps({"schema_version": 1, "updated_at": datetime.fromtimestamp(old_ts, tz=timezone.utc).isoformat(), "accounts": {"a": {"account_id": "a", "currency": "USD", "equity": 1, "daily_buffer": 1, "max_dd_buffer": 1}}})
            conn.request("POST", "/api/telemetry/fleet", old_payload, {"Content-Type": "application/json", "Authorization": "Bearer VALIDTOKEN_12345678901234567890123"})
            r = conn.getresponse()
            assert r.status == 422, f"Timestamp test failed (got {r.status})"
            r.read()

            # Test 6: Success
            conn.request("POST", "/api/telemetry/fleet", valid_payload, {"Content-Type": "application/json", "Authorization": "Bearer VALIDTOKEN_12345678901234567890123"})
            r = conn.getresponse()
            assert r.status == 200, f"Success test failed (got {r.status})"
            r.read()
            assert os.path.exists(os.path.join(temp_dir, "fleet_snapshot.json")), "File not saved"

            # Test 7: Journal Schema- & Header-Validierung
            bad_journal_payload = json.dumps({
                "schema_version": 1,
                "updated_at": datetime.now(timezone.utc).isoformat(),
                "csv_content": "foo,bar\n1,2"
            })
            conn.request("POST", "/api/telemetry/journal", bad_journal_payload, {"Content-Type": "application/json", "Authorization": "Bearer VALIDTOKEN_12345678901234567890123"})
            r = conn.getresponse()
            assert r.status == 400, f"Journal header validation test failed (got {r.status})"
            r.read()

            # Test 8: Journal Atomare Speicherung
            valid_csv_content = "id,account_name,symbol,status\nT1,FTMO,EURUSD=X,OPEN\n"
            valid_journal_payload = json.dumps({
                "schema_version": 1,
                "updated_at": datetime.now(timezone.utc).isoformat(),
                "csv_content": valid_csv_content
            })
            conn.request("POST", "/api/telemetry/journal", valid_journal_payload, {"Content-Type": "application/json", "Authorization": "Bearer VALIDTOKEN_12345678901234567890123"})
            r = conn.getresponse()
            assert r.status == 200, f"Journal save test failed (got {r.status})"
            r.read()
            journal_target_path = os.path.join(temp_dir, "netcup_trade_journal.csv")
            assert os.path.exists(journal_target_path), "Journal file not saved"
            with open(journal_target_path, 'r', encoding='utf-8', newline='') as jf:
                assert jf.read() == valid_csv_content, "Journal content mismatch"
            
            logging.info("All self-tests passed successfully.")
            sys.exit(0)
        except Exception as e:
            logging.error(f"Self-test failed: {e}")
            sys.exit(1)
        finally:
            server.shutdown()
            t.join()

if __name__ == '__main__':
    load_environment()
    
    if "--self-test" in sys.argv:
        run_self_test()
    
    secret = os.environ.get("TELEMETRY_SECRET_TOKEN", "")
    if len(secret) >= 32:
        TOKEN_VALID = True
    else:
        logging.critical("CRITICAL: TELEMETRY_SECRET_TOKEN is missing or less than 32 chars. POST requests will be rejected with 503.")

    host = os.environ.get("TELEMETRY_BIND_HOST", "127.0.0.1")
    port = int(os.environ.get("TELEMETRY_BIND_PORT", "8502"))
    
    server = TelemetryHTTPServer((host, port), TelemetryRequestHandler)
    
    def shutdown(signum, frame):
        logging.info("Received termination signal, shutting down gracefuly...")
        threading.Thread(target=server.shutdown).start()
    
    signal.signal(signal.SIGINT, shutdown)
    signal.signal(signal.SIGTERM, shutdown)
    
    logging.info(f"Telemetry receiver starting on {host}:{port}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    logging.info("Server stopped.")