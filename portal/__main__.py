"""Start the read-only portal:  PORTAL_PASSWORD=... python -m portal

Binds to 127.0.0.1:8080 by default (reach it via an SSH tunnel). Override with
PORTAL_HOST / PORTAL_PORT — inside Docker the compose file sets 0.0.0.0 but
publishes the port on the host's 127.0.0.1 only.
"""
import os

import uvicorn

from .app import create_app

if __name__ == "__main__":
    uvicorn.run(create_app(),
                host=os.getenv("PORTAL_HOST", "127.0.0.1"),
                port=int(os.getenv("PORTAL_PORT", "8080")))
