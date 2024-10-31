from datetime import timedelta
from unittest import mock

import pytest
from django.core.management import call_command
from django.test import TestCase
from django.test.utils import override_settings

from license_manager.apps.subscriptions.constants import (
    ACTIVATED,
    ASSIGNED,
    EXPIRED_LICENSE_UNLINKED,
    REVOKED,
    UNASSIGNED,
)
from license_manager.apps.subscriptions.models import LicenseEvent
from license_manager.apps.subscriptions.tests.factories import (
    CustomerAgreementFactory,
    LicenseFactory,
    SubscriptionPlanFactory,
)
from license_manager.apps.subscriptions.utils import localized_utcnow


@pytest.mark.django_db
class UnlinkExpiredLicensesCommandTests(TestCase):
    command_name = 'unlink_expired_licenses'
    today = localized_utcnow()
    customer_uuid = '76b933cb-bf2a-4c1e-bf44-4e8a58cc37ae'

    def _create_expired_plan_with_licenses(
        self,
        unassigned_licenses_count=1,
        assigned_licenses_count=2,
        activated_licenses_count=3,
        revoked_licenses_count=4,
        start_date=today - timedelta(days=7),
        expiration_date=today,
        expiration_processed=False
    ):
        """
        Creates a plan with licenses. The plan is expired by default.
        """
        customer_agreement = CustomerAgreementFactory(enterprise_customer_uuid=self.customer_uuid)
        expired_plan = SubscriptionPlanFactory.create(
            customer_agreement=customer_agreement,
            start_date=start_date,
            expiration_date=expiration_date,
            expiration_processed=expiration_processed
        )

        LicenseFactory.create_batch(unassigned_licenses_count, status=UNASSIGNED, subscription_plan=expired_plan)
        LicenseFactory.create_batch(assigned_licenses_count, status=ASSIGNED, subscription_plan=expired_plan)
        LicenseFactory.create_batch(activated_licenses_count, status=ACTIVATED, subscription_plan=expired_plan)
        LicenseFactory.create_batch(revoked_licenses_count, status=REVOKED, subscription_plan=expired_plan)

        return expired_plan

    def _get_allocated_license_uuids(self, subscription_plan):
        return [str(license.uuid) for license in subscription_plan.licenses.filter(status__in=[ASSIGNED, ACTIVATED])]

    @override_settings(
        CUSTOMERS_WITH_EXPIRED_LICENSES_UNLINKING_ENABLED=['76b933cb-bf2a-4c1e-bf44-4e8a58cc37ae']
    )
    @mock.patch(
        'license_manager.apps.subscriptions.management.commands.unlink_expired_licenses.EnterpriseApiClient',
        return_value=mock.MagicMock()
    )
    def test_expired_licenses_unlinking(self, mock_enterprise_client):
        """
        Verify that expired licenses unlinking working as expected.
        """
        today = localized_utcnow()

        # create a plan that is expired but difference between expiration_date and today is less than 90
        self._create_expired_plan_with_licenses()
        # create a plan that is expired 90 days ago
        plan_expired_90_days_ago = self._create_expired_plan_with_licenses(
            start_date=today - timedelta(days=150),
            expiration_date=today - timedelta(days=90)
        )

        call_command(self.command_name)

        # verify that correct licenses from desired subscription plan were recorded in database
        for license_event in LicenseEvent.objects.all():
            assert license_event.license.subscription_plan.uuid == plan_expired_90_days_ago.uuid
            assert license_event.event_name == EXPIRED_LICENSE_UNLINKED

        # verify that call to unlink_users endpoint has correct user emails
        mock_client_call_args = mock_enterprise_client().bulk_unlink_enterprise_users.call_args_list[0]
        assert mock_client_call_args.args[0] == self.customer_uuid
        assert sorted(mock_client_call_args.args[1]['user_emails']) == sorted([
            license.user_email for license in plan_expired_90_days_ago.licenses.filter(
                status__in=[ASSIGNED, ACTIVATED]
            )
        ])

    @override_settings(
        CUSTOMERS_WITH_EXPIRED_LICENSES_UNLINKING_ENABLED=['76b933cb-bf2a-4c1e-bf44-4e8a58cc37ae']
    )
    @mock.patch(
        'license_manager.apps.subscriptions.management.commands.unlink_expired_licenses.EnterpriseApiClient',
        return_value=mock.MagicMock()
    )
    def test_expired_licenses_other_active_licenses(self, mock_enterprise_client):
        """
        Verify that no unlinking happens when all expired licenses has other active licenses.
        """
        assert LicenseEvent.objects.count() == 0
        today = localized_utcnow()

        # create a plan that is expired 90 days ago
        plan_expired_90_days_ago = self._create_expired_plan_with_licenses(
            start_date=today - timedelta(days=150),
            expiration_date=today - timedelta(days=90)
        )
        # just another plan
        another_plan = self._create_expired_plan_with_licenses(
            start_date=today - timedelta(days=150),
            expiration_date=today + timedelta(days=10)
        )

        # fetch user emails from the expired plan
        user_emails = list(plan_expired_90_days_ago.licenses.filter(
            status__in=[ASSIGNED, ACTIVATED]
        ).values_list('user_email', flat=True))

        # assigned the above emails to licenses to create the test scenario where a learner has other active licenses
        for license in another_plan.licenses.filter(status__in=[ASSIGNED, ACTIVATED]):
            license.user_email = user_emails.pop()
            license.save()

        call_command(self.command_name)

        # verify that no records were created in database for LicenseEvent
        assert LicenseEvent.objects.count() == 0

        # verify that no calls have been made to the unlink_users endpoint.
        assert mock_enterprise_client().bulk_unlink_enterprise_users.call_count == 0
