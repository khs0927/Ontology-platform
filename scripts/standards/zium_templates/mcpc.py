"""Minimal stdio MCP client: mcpc.py <exe> <tool|-> [json-args] [timeout]"""
import sys, json, subprocess, threading, queue, time
sys.stdout.reconfigure(encoding="utf-8")
exe, tool = sys.argv[1], sys.argv[2]
args = json.loads(open(sys.argv[3][1:],encoding="utf-8").read() if sys.argv[3].startswith("@") else sys.argv[3]) if len(sys.argv) > 3 else {}
to = float(sys.argv[4]) if len(sys.argv) > 4 else 60
p = subprocess.Popen([exe], stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
q = queue.Queue()
threading.Thread(target=lambda: [q.put(l) for l in p.stdout], daemon=True).start()
def send(o): p.stdin.write((json.dumps(o)+"\n").encode()); p.stdin.flush()
def wait(i):
    end = time.time()+to
    while time.time() < end:
        try: l = q.get(timeout=1)
        except queue.Empty: continue
        try: o = json.loads(l)
        except Exception: continue
        if o.get("id") == i: return o
    return {"timeout": i}
send({"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2024-11-05","capabilities":{},"clientInfo":{"name":"probe","version":"0"}}})
wait(1); send({"jsonrpc":"2.0","method":"notifications/initialized"})
if tool == "-":
    send({"jsonrpc":"2.0","id":2,"method":"tools/list"}); r = wait(2)
    names = [t["name"] for t in r.get("result",{}).get("tools",[])]
    print(len(names), " ".join(names))
elif tool == "?":
    send({"jsonrpc":"2.0","id":2,"method":"tools/list"}); r = wait(2)
    for t in r.get("result",{}).get("tools",[]):
        if t["name"] in args: print(t["name"], json.dumps(t.get("inputSchema"), ensure_ascii=False)[:1500], "|", (t.get("description") or "")[:300])
elif tool == "+":
    for i,(t,a) in enumerate(args, start=10):
        send({"jsonrpc":"2.0","id":i,"method":"tools/call","params":{"name":t,"arguments":a}})
        print("##", t, json.dumps(wait(i), ensure_ascii=False)[:4000])
else:
    send({"jsonrpc":"2.0","id":3,"method":"tools/call","params":{"name":tool,"arguments":args}})
    print(json.dumps(wait(3), ensure_ascii=False)[:5000])
p.kill()
