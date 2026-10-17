"""Create an ignored server interpolation file with locally generated secrets."""
import os
from pathlib import Path
import secrets


path = Path(".env.server")
if path.exists():
    print(".env.server already exists and was preserved. No secrets were read or printed.")
else:
    source = Path(".env.server.example").read_text(encoding="utf-8")
    source = source.replace("LOBSTER_PROXY_TOKEN=\n", "LOBSTER_PROXY_TOKEN=" + secrets.token_urlsafe(48) + "\n")
    source = source.replace("OPERATOR_TOKEN=\n", "OPERATOR_TOKEN=" + secrets.token_urlsafe(48) + "\n")
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as file: file.write(source)
    print("Created ignored .env.server with different random proxy/operator secrets. Fill your domain/provider settings locally. Nothing was deployed and no secret was printed.")
