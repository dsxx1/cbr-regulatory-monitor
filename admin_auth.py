"""Passwordless access boundary, explicitly requested by the owner."""
import ipaddress


class OwnerAuth:
    def __init__(self,root=None):
        pass

    @staticmethod
    def local(address):
        try:return ipaddress.ip_address(address).is_loopback
        except ValueError:return False
