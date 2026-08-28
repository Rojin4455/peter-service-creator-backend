from django.contrib.auth.models import AnonymousUser
from rest_framework import authentication, exceptions, permissions

from .models import DashboardApiKey


class DashboardAPIKeyAuthentication(authentication.BaseAuthentication):
    """
    Authenticate via:
      X-API-Key: <key>
    or
      Authorization: Api-Key <key>
    """

    header_name = 'HTTP_X_API_KEY'
    keyword = 'Api-Key'

    def authenticate(self, request):
        raw_key = request.META.get(self.header_name)
        if not raw_key:
            auth = authentication.get_authorization_header(request).decode('utf-8')
            if auth:
                parts = auth.split(None, 1)
                if len(parts) == 2 and parts[0] == self.keyword:
                    raw_key = parts[1].strip()

        if not raw_key:
            return None

        api_key = DashboardApiKey.authenticate_key(raw_key)
        if api_key is None:
            raise exceptions.AuthenticationFailed('Invalid or inactive API key.')

        return (AnonymousUser(), api_key)


class HasDashboardAPIKey(permissions.BasePermission):
    message = 'Valid dashboard API key required.'

    def has_permission(self, request, view):
        return isinstance(request.auth, DashboardApiKey) and request.auth.is_active
