"""
Exceptions raised by functions exposed by the Subscriptions app.
"""


class LicenseRevocationError(Exception):

    def __init__(self, license_uuid, failure_reason):
        """
        Arguments:
            license_uuid (uuid4): the unique identifier for a license
            failure_reason (str): the reason for the license revocation error
        """
        super().__init__()
        self.license_uuid = license_uuid
        self.failure_reason = failure_reason

    def __str__(self):
        return "Attempted license revocation FAILED for License [{}]. Reason: {}".format(
            self.license_uuid,
            self.failure_reason,
        )


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
