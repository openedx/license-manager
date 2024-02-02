from functools import cached_property
from rest_framework.exceptions import ParseError, status
from license_manager.apps.api_client.lms import LMSApiClient

from license_manager.apps.api import utils


class UserDetailsFromJwtMixin:
    """
    Mixin for retrieving user information from the jwt.
    """

    @cached_property
    def decoded_jwt(self):
        """
        Expects `self.request` to be explicitly defined.
        """
        if not getattr(self, 'request', None):
            raise Exception(f'{self.__class__} must have a request field.')

        return utils.get_decoded_jwt(self.request)

    @cached_property
    def lms_user_id(self):
        try:
            return utils.get_key_from_jwt(self.decoded_jwt, 'user_id')
        except ParseError:
            lms_client = LMSApiClient()
            user_id = lms_client.fetch_lms_user_id(self.request.user.email)
            return user_id

    @property
    def user_email(self):
        return utils.get_key_from_jwt(self.decoded_jwt, 'email')
