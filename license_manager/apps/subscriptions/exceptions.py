"""
Exceptions raised by functions exposed by the Subscriptions app.
"""


class LicenseRevocationError(Exception):

    def __init__(self, license_uuid):
        super(LicenseRevocationError, self).__init__()
        self.license_uuid = license_uuid

    def __str__(self):
        return "Attempted license revocation FAILED for License [{}]".format(
            self.license_uuid,
        )
