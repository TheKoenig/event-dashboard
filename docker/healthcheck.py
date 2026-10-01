"""Container health check: exit 0 if the dashboard answers on its configured port."""

import os
import ssl
import sys
import urllib.request

tls = bool(os.environ.get("EVENT_DASHBOARD_SSL_CERTFILE"))
port = os.environ.get("EVENT_DASHBOARD_PORT") or ("443" if tls else "80")
url = f"{'https' if tls else 'http'}://127.0.0.1:{port}/api/languages"

# Talk to the local server directly: no proxy, and accept the (possibly self-signed) certificate.
context = ssl._create_unverified_context()  # noqa: S323
opener = urllib.request.build_opener(
    urllib.request.ProxyHandler({}), urllib.request.HTTPSHandler(context=context)
)
try:
    with opener.open(url, timeout=5) as response:  # noqa: S310
        sys.exit(0 if response.status == 200 else 1)
except Exception as exc:
    print(f"unhealthy: {exc}", file=sys.stderr)
    sys.exit(1)
