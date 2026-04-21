import ipaddress
from django.core.exceptions import PermissionDenied


class InternalNetworkMiddleware:
    """
    Middleware that restricts access to the login and registration endpoints
    to requests coming from internal networks only.
    """
    def __init__(self, get_response):
        self.get_response = get_response
        self.internal_networks = [
            ipaddress.ip_network('10.0.0.0/8'),
            ipaddress.ip_network('172.16.0.0/12'),
            ipaddress.ip_network('192.168.0.0/16'),
            ipaddress.ip_network('127.0.0.0/8'),
            ipaddress.ip_network('::1/128'),
        ]

        self.restricted_paths = [
            '/accounts/login/',
            '/accounts/register/',
            '/accounts/api/login/',
            '/accounts/api/register/',
            '/admin/login/',
        ]

    def __call__(self, request):
        path = request.path

        if any(path.startswith(rp) for rp in self.restricted_paths):
            client_ip = request.META.get('HTTP_X_FORWARDED_FOR')
            if client_ip:
                client_ip = client_ip.split(',')[0].strip()
            else:
                client_ip = request.META.get('REMOTE_ADDR')

            if client_ip:
                try:
                    ip = ipaddress.ip_address(client_ip)
                    is_internal = any(ip in net for net in self.internal_networks)
                    if not is_internal:
                        raise PermissionDenied("Dostęp do logowania tylko z sieci wewnętrznej.")
                except ValueError:
                    raise PermissionDenied("Nieprawidłowy adres IP.")

        return self.get_response(request)
