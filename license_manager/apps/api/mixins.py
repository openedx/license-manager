from functools import cached_property

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

    @property
    def lms_user_id(self):
        return utils.get_key_from_jwt(self.decoded_jwt, 'user_id')

    @property
    def user_email(self):
        return utils.get_key_from_jwt(self.decoded_jwt, 'email')
