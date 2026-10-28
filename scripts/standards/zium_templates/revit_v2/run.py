"""run.py <part.cs> [timeout]: prelude + part -> rvt-mcp revit_send_code_to_revit; prints log."""
import sys, json, subprocess, os
here = os.path.dirname(os.path.abspath(__file__))
code = open(os.path.join(here, "00_prelude.cs"), encoding="utf-8").read() + "\n" + open(sys.argv[1], encoding="utf-8").read() + "\nreturn L.ToString();\n"
a = os.path.join(os.environ.get("TEMP", "."), "zium_run_args.json")
json.dump({"code": code}, open(a, "w", encoding="utf-8"), ensure_ascii=False)
exe = os.path.expandvars(r"%LOCALAPPDATA%\RvtMcp\rvt\server\current\rvt-mcp.exe")
subprocess.run([sys.executable, os.path.join(here, "..", "mcpc.py"), exe, "revit_send_code_to_revit", "@" + a, sys.argv[2] if len(sys.argv) > 2 else "600"])
