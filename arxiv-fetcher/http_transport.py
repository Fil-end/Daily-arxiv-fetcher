"""Explicit proxy transport shared by discovery, full text and model calls."""
from pathlib import Path
from urllib.parse import urlsplit

import requests
import yaml


SESSION = requests.Session()
FALLBACK_SESSION = requests.Session()
for session in (SESSION, FALLBACK_SESSION):
    session.headers["User-Agent"] = "PersonalLiteratureFetcher/4.1"


def configure_network(config):
    """Use the local Mihomo listener without loading node credentials."""
    network = config.get("network", {})
    proxy = network.get("proxy_url")
    if not proxy and network.get("mihomo_profile"):
        try:
            profile = yaml.safe_load(Path(network["mihomo_profile"]).read_text(encoding="utf-8"))
            port = profile.get("mixed-port") or profile.get("port")
            if not isinstance(port, int) or isinstance(port, bool) or not 1 <= port <= 65535:
                raise ValueError()
        except (OSError, yaml.YAMLError, ValueError, AttributeError):
            raise ValueError("Cannot read a valid HTTP proxy port from the Mihomo profile") from None
        proxy = f"http://127.0.0.1:{port}"
    if network.get("require_proxy") and not proxy:
        raise ValueError("A proxy is required; configure network.proxy_url or network.mihomo_profile")
    if proxy:
        parts = urlsplit(proxy)
        if parts.scheme not in ("http", "https") or not parts.hostname:
            raise ValueError("network.proxy_url must be an HTTP(S) proxy URL")
    for session in (SESSION, FALLBACK_SESSION):
        session.proxies.clear()
        session.trust_env = not bool(proxy)
        if proxy:
            session.proxies.update(http=proxy, https=proxy)
        session.verify = network.get("ca_bundle") or True
    if proxy:
        print(f"[Network] Proxy required: {parts.hostname}:{parts.port}; TLS verification enabled", flush=True)

