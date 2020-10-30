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


class InsufficientLicensesForRenewalError(Exception):
    """
    Exception raised during renewal processing when the linked subscription does not have enough unassigned licenses to
    remove when renewing with a smaller number of licenses.

    Example: A customer has a SubscriptionPlan with 100 licenses, 50 of which are unassigned on the renewal effective
    date. If they have a renewal being processed that calls for more than 50 licenses, this exception should be raised.
    """
    def __init__(self, subscription_for_renewal, num_licenses_to_remove, num_existing_unassigned_licenses):
        """
        Args:
            subscription_for_renewal (SubscriptionPlan): The subscription that was unable to be renewed.
            num_licenses_to_remove (int): The number of licenses that need to be removed from the subscription to match
                the number for renewal.
            num_existing_unassigned_licenses (int): How many unassigned licenses the subscription has prior to renewal.
        """
        super().__init__()
        self.subscription_for_renewal = subscription_for_renewal
        self.num_licenses_to_remove = num_licenses_to_remove
        self.num_existing_unassigned_licenses = num_existing_unassigned_licenses

    def __str__(self):
        message = ('Subscription Renewal failed for SubscriptionPlan with uuid: {}. The renewal calls for {} licenses'
        ' to be removed, but the subscription only has {} unassigned licenses to remove.')
        return message.format(
            self.subscription_for_renewal.uuid,
            self.num_licenses_to_remove,
            self.num_existing_unassigned_licenses,
        )
