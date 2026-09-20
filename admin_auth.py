"""Owner session: login only on loopback; key never sent over the LAN."""
import hmac
import ipaddress
import secrets
import time
from http.cookies import SimpleCookie
from pathlib import Path


class OwnerAuth:
    def __init__(self, root):
        self.path = Path(root)/'owner.key'
        if not self.path.exists(): self.path.write_text(secrets.token_urlsafe(40),encoding='ascii')
        self.key = self.path.read_text(encoding='ascii').strip()
        self.sessions = {}

    @staticmethod
    def local(address):
        try: return ipaddress.ip_address(address).is_loopback
        except ValueError: return False

    def login(self, address, key):
        if not self.local(address) or not isinstance(key,str) or not hmac.compare_digest(self.key,key): return None
        token=secrets.token_urlsafe(40)
        self.sessions[token]=time.time()+8*3600
        return token

    def allowed(self, address, cookie):
        if not self.local(address): return False
        try:
            jar=SimpleCookie();jar.load(cookie or '')
            token=jar['monitor_owner'].value
            return self.sessions.get(token,0)>time.time()
        except (KeyError,ValueError): return False
