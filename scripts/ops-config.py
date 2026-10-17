"""Create a private local recovery key without printing it or enabling uploads."""
import os
from pathlib import Path
import secrets

path = Path(".env.ops")
if path.exists(): print(".env.ops already exists and was preserved. No secret was read or printed.")
else:
    source = Path(".env.ops.example").read_text(encoding="utf-8").replace("OPS_ENCRYPTION_KEY=\n", "OPS_ENCRYPTION_KEY=" + secrets.token_hex(32) + "\n")
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(descriptor,"w",encoding="utf-8",newline="\n") as file: file.write(source)
    print("Created ignored .env.ops with a random recovery encryption key. Store a separate secure recovery copy. Uploads remain disabled; no key was printed.")
