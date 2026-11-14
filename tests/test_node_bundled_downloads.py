"""Exercise the embedded Nodes Lab helper replacement without networking or VPS."""
from pathlib import Path
import re
import subprocess
import tempfile

src = Path("node-install.sh").read_text(encoding="utf-8")
start = 'python3 - "$STAGE" <<\'PY_LOCAL_DEPS\'\n'
end = "\nPY_LOCAL_DEPS"
assert src.count(start) == 1
payload = src.split(start, 1)[1].split(end, 1)[0]
pattern = re.compile(r'^cat > "\$STAGE/(?P<name>wpo-nodes-lab(?:-v\d+)?-install\.sh)" <<\'(?P<marker>__WPO_EMBED_V\d+_END_736a4b__)\'\n(?P<body>[\s\S]*?)\n(?P=marker)$', re.M)
matches = list(pattern.finditer(src))
assert len(matches) == 26, f"Expected 26 embedded node steps: {len(matches)}"
assets = {2: "wpo-node-agent-install-v2.sh",
          10: "wpo-node-agent-install-v2.sh",
          11: "wpo-node-agent-install-v2.sh",
          12: "wpo-node-agent-install-v2.sh",
          13: "wpo-node-geo-v13.py",
          20: "wpo-node-autotemplate-v20.py",
          23: "wpo-node-agent-install-v2.sh"}
with tempfile.TemporaryDirectory(prefix="wpo-node-bundle-") as temp:
    root = Path(temp)
    for item in matches:
        (root / item["name"]).write_text(item["body"].rstrip("\n") + "\n", encoding="utf-8")
    for name in set(assets.values()):
        (root / name).write_bytes(Path(name).read_bytes())
    completed = subprocess.run(["python3", "-", temp], input=payload, text=True, capture_output=True, timeout=15)
    assert completed.returncode == 0, (completed.stdout, completed.stderr)
    for version, asset in assets.items():
        script = root / f"wpo-nodes-lab-v{version}-install.sh"
        text = script.read_text(encoding="utf-8")
        assert f'cp -- {str(root / asset)!r}' not in text, "Unexpected Python quote-style output"
        assert f'cp -- {root / asset} "$TMP"' in text, (version, text[:350])
        assert not re.search(r'curl -4fsSL --retry 3 --connect-timeout.*' + re.escape(asset), text), version
        subprocess.run(["bash", "-n", str(script)], check=True, capture_output=True, timeout=5)
print("PASS: all 26 embedded node steps; seven legacy helper downloads replaced locally; syntax valid")
