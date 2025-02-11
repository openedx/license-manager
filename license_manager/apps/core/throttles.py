"""
Custom DRF user-throttling classes
so that we can throttle both bursty and sustained
throughtput.
"""
from django.conf import settings
from rest_framework.throttling import UserRateThrottle


class PrivelegedUserThrottle(UserRateThrottle):
    """
    Skips throttling is the requesting authenticated user
    is in the list of priveleged user ids.
    is staff or superuser.
    """
    def allow_request(self, request, view):
        user = request.user

        if user and user.is_authenticated and user.id in settings.PRIVELEGED_USER_IDS:
            return True

        return super().allow_request(request, view)


class UserBurstRateThrottle(PrivelegedUserThrottle):
    scope = 'user_burst'


class UserSustainedRateThrottle(PrivelegedUserThrottle):
    scope = 'user_sustained'
