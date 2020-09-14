from django.test import TestCase

from license_manager.apps.subscriptions.constants import UNASSIGNED
from license_manager.apps.subscriptions.tests.factories import (
    LicenseFactory,
    SubscriptionPlanFactory,
)


class SubscriptionsModelFactoryTests(TestCase):
    """
    Tests on the model factories for subscriptions.
    """

    def test_license_factory(self):
        """
        Verify an unassigned license is created and associated with a subscription.
        """
        license = LicenseFactory()
        self.assertEqual(license.status, UNASSIGNED)
        subscription_licenses = [license.uuid for license in license.subscription_plan.licenses.all()]
        self.assertIn(license.uuid, subscription_licenses)

    def test_subscription_factory(self):
        """
        Verify an unexpired subscription plan is created by default.
        """
        subscription = SubscriptionPlanFactory()
        self.assertTrue(subscription.start_date < subscription.expiration_date)

    def test_subscription_factory_licenses(self):
        """
        Verify a subscription plan factory can have licenses associated with it.
        """
        subscription = SubscriptionPlanFactory()
        licenses = LicenseFactory.create_batch(5)
        subscription.licenses.set(licenses)
        # Verify the subscription plan uuid is correctly set on the licenses
        license = subscription.licenses.first()
        self.assertEqual(subscription.uuid, license.subscription_plan.uuid)
