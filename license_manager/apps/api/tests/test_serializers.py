import ddt
from django.test import TestCase
from pytest import mark

from license_manager.apps.api.serializers import (
    CustomerAgreementSerializer,
    LicenseAdminBulkActionSerializer,
)
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
        self.inactive_subscription_plans = SubscriptionPlanFactory.create_batch(
            3, customer_agreement=customer_agreement, is_active=False
        )
        self.customer_agreement = customer_agreement

    @ddt.data(True, False)
    def test_serialize_active_plans_only(self, active_plans_only):
        """
        Tests that only active plans are serialized if active_plans_only = True in context.
        """
        serializer = CustomerAgreementSerializer(
            self.customer_agreement, context={'active_plans_only': active_plans_only}
        )
        data = serializer.data

        only_active_plans = all(plan['is_active'] for plan in data['subscriptions'])

        self.assertEqual(only_active_plans, active_plans_only)


@ddt.ddt
class TestLicenseAdminBulkActionSerializer(TestCase):
    """
    Tests for the LicenseAdminBulkActionSerializer.
    """

    @ddt.data(({}, False))
    @ddt.data(({'user_emails': []}, False))
    @ddt.data(({'filters': []}, False))
    @ddt.data((
        {
            'user_emails': ['edx@example.com'],
            'filters': [{'name': 'user_email', 'filter_value': 'edx'}]
        },
        False,
    ))
    @ddt.data(({'user_emails': ['edx@example.com']}, True))
    @ddt.data((
        {
            'filters': [{'name': 'user_email', 'filter_value': 'edx'}]
        },
        True,
    ))
    @ddt.data((
        {
            'filters': [{'name': 'unsupported_filter', 'filter_value': 'edx'}]
        },
        False,
    ))
    @ddt.data((
        {
            'filters': [{'name': 'status_in', 'filter_value': 'not a list'}]
        },
        False,
    ))
    @ddt.data((
        {
            'filters': [{'name': 'status_in', 'filter_value': ['assigned']}]
        },
        True,
    ))
    @ddt.data((
        {
            'filters': [
                {'name': 'user_email', 'filter_value': 'edx'},
                {'name': 'status_in', 'filter_value': ['assigned']}
            ]
        },
        True,
    ))
    @ddt.unpack
    def test_validate_data(self, data, expected_is_valid):
        serializer = LicenseAdminBulkActionSerializer(data=data)
        self.assertEqual(serializer.is_valid(), expected_is_valid)
