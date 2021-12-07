import ddt
from django.test import TestCase
from pytest import mark

from license_manager.apps.api.serializers import CustomerAgreementSerializer
from license_manager.apps.subscriptions.tests.factories import (
    CustomerAgreementFactory,
    SubscriptionPlanFactory,
)


@ddt.ddt
@mark.django_db
class TestCustomerAgreementSerializer(TestCase):
    """
    Tests for the CustomerAgreementSerializer.
    """

    def setUp(self):
        super().setUp()
        customer_agreement = CustomerAgreementFactory()
        self.active_subscription_plans = SubscriptionPlanFactory.create_batch(2, customer_agreement=customer_agreement)
        self.inactive_subscription_plans = SubscriptionPlanFactory.create_batch(3, customer_agreement=customer_agreement, is_active=False)
        self.customer_agreement = customer_agreement

    @ddt.data(True, False)
    def test_serialize_active_plans_only(self, active_plans_only):
        """
        Tests that only active plans are serialized if active_plans_only = True in context.
        """
        serializer = CustomerAgreementSerializer(self.customer_agreement, context={'active_plans_only': active_plans_only})
        data = serializer.data

        only_active_expirations = all([expiration['is_active'] for expiration in data['ordered_subscription_plan_expirations']])
        only_active_plans = all([plan['is_active'] for plan in data['subscriptions']])

        all_active = only_active_expirations and only_active_plans
        self.assertEqual(all_active, active_plans_only)
