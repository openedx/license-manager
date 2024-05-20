"""
Permission classes for Subscriptions API
"""
from django.conf import settings
from rest_framework import permissions


class CanRetireUser(permissions.BasePermission):
    """
    Grant access to the user retirement API for the service user, and to superusers. This mimics the
    retirement permissions check in edx-platform.
    """

    def has_permission(self, request, view):
        return request.user.username == settings.RETIREMENT_SERVICE_WORKER_USERNAME or request.user.is_superuser


class CanProvisionLicenses(permissions.BasePermission):
    """
    Grant access to the user retirement API for the service user, and to superusers. This mimics the
    retirement permissions check in edx-platform.
    """
    ALLOWED_API_GROUPS = ['license_provisioning_admins']
    message = 'User is not allowed to access the view.'

    def has_permission(self, request, view):
        return (
            super().has_permission(request, view) and (
                request.user.groups.filter(name__in=self.ALLOWED_API_GROUPS).exists()
            )
        )
    
