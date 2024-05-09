"""
Exceptions raised by functions exposed by the Subscriptions app.
"""


class CustomerAgreementError(Exception):
    """
    A general exception dealing with CustomerAgreements.
    """


class LicenseError(Exception):
    """
    General exception about some license action
    that accepts a license UUID and some failure reason.
    """
    action = None

    def __init__(self, license_uuid, failure_reason):
        """
        Arguments:
            license_uuid (uuid4): the unique identifier for a license
            failure_reason (str): the reason for the license-related failure
        """
        super().__init__()
        self.license_uuid = license_uuid
        self.failure_reason = failure_reason

    def __str__(self):
        return "Action: {} failed for license: {} because: {}".format(
            self.action,
            self.license_uuid,
            self.failure_reason,
        )


class LicenseRevocationError(LicenseError):
    """
    Exception raised for failed license revocations.
    """
    action = 'license revocation'


class LicenseNotFoundError(Exception):
    """
    Raised when no license exists for a given (email, subscription_plan, statuses) combination.
    """
    def __init__(self, user_email, subscription_plan, license_statuses):
        super().__init__()
        self.user_email = user_email
        self.subscription_plan = subscription_plan
        self.license_statuses = license_statuses

    def __str__(self):
        return "No license for email {} exists in plan {} with a status in {}".format(
            self.user_email,
            self.subscription_plan.uuid,
            self.license_statuses,
        )


class RenewalProcessingError(Exception):
    """
    An Exception indicating that a SubscriptionPlanRenewal
    cannot be processed.
    """


class InvalidSubscriptionPlanPayloadError(Exception):
    """
    An exception indicating that the provided data (payload) was invalid
    and prevented the creation or update of a subscription plan.
    """

    def __init__(self, message):
        """
        Arguments:
            message (str): error message raised
        """
        super().__init__('Invalid payload.', message)
        self.message = message

    def __str__(self):
        return "An error occurred: {}".format(
            self.message,
        )


class UnprocessableSubscriptionPlanExpirationError(Exception):
    """
    An exception indicating that a subscription plan's
    expiration cannot be processed.
    """


class UnprocessableSubscriptionPlanFreezeError(Exception):
    """
    An exception indicating that a subscription plan cannot be
    frozen to delete unused licenses.
    """


class LicenseActivationError(LicenseError):
    """
    An exception that occurs during license activation.
    """
    action = 'activation'


class LicenseToActivateIsRevokedError(LicenseActivationError):
    """
    An exception that occurs when the license to activate is revoked.
    """
    action = 'activation'

    def __init__(self, license_uuid):
        """
        Arguments:
            license_uuid (uuid4): the unique identifier for a license
        """
        super().__init__(license_uuid, 'Cannot activate a revoked license.')


class LicenseActivationMissingError(LicenseActivationError):
    """
    An exception that occurs when no license with a given activation_key is found.
    """
    action = 'activation'
