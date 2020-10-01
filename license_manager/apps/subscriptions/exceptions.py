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
        super(LicenseRevocationError, self).__init__()
        self.license_uuid = license_uuid
        self.failure_reason = failure_reason

    def __str__(self):
        return "Attempted license revocation FAILED for License [{}]. Reason: {}".format(
            self.license_uuid,
            self.failure_reason,
        )
