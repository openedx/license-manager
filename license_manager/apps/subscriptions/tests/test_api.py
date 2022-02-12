import uuid
from math import ceil
from unittest import mock

import ddt
import freezegun
from django.test import TestCase
from requests.exceptions import HTTPError

from license_manager.apps.subscriptions import api, constants, exceptions, utils
from license_manager.apps.subscriptions.models import (
    CustomerAgreement,
    SubscriptionPlan,
)
from license_manager.apps.subscriptions.tests.factories import (
    CustomerAgreementFactory,
    LicenseFactory,
    SubscriptionPlanFactory,
    SubscriptionPlanRenewalFactory,
)


NOW = utils.localized_utcnow()


@ddt.ddt
class RenewalProcessingTests(TestCase):
    """
    Tests for the processing of a SubscriptionPlanRenewal.
    """
    def test_cannot_renew_for_fewer_licenses(self):
        prior_plan = SubscriptionPlanFactory()
        LicenseFactory.create_batch(
            5,
            subscription_plan=prior_plan,
            status=constants.ACTIVATED,
        )
        renewal = SubscriptionPlanRenewalFactory(
            number_of_licenses=2,
            prior_subscription_plan=prior_plan,
        )

        expected_message = 'Cannot renew for fewer than the number of original activated licenses.'
        with self.assertRaisesRegex(exceptions.RenewalProcessingError, expected_message):
            api.renew_subscription(renewal)

    def test_cannot_renew_with_existing_assigned_future_licenses(self):
        future_plan = SubscriptionPlanFactory()
        LicenseFactory.create_batch(
            5,
            subscription_plan=future_plan,
            status=constants.ACTIVATED,
        )
        renewal = SubscriptionPlanRenewalFactory(
            renewed_subscription_plan=future_plan,
            number_of_licenses=20,
        )

        expected_message = 'there are existing licenses in the renewed plan that are activated'
        with self.assertRaisesRegex(exceptions.RenewalProcessingError, expected_message):
            api.renew_subscription(renewal)

    def test_cannot_renew_too_many_existing_unassigned_licenses(self):
        future_plan = SubscriptionPlanFactory()
        LicenseFactory.create_batch(
            50,
            subscription_plan=future_plan,
            status=constants.UNASSIGNED,
        )
        renewal = SubscriptionPlanRenewalFactory(
            renewed_subscription_plan=future_plan,
            number_of_licenses=20,
        )

        expected_message = 'More licenses exist than were requested to be renewed'
        with self.assertRaisesRegex(exceptions.RenewalProcessingError, expected_message):
            api.renew_subscription(renewal)

    def _assert_all_licenses_renewed(self, future_plan):
        """
        Helper to assert that future license fields are updated with expected values.
        """
        expected_activation_datetime = future_plan.start_date

        future_licenses = future_plan.licenses.filter(
            status__in=(constants.ASSIGNED, constants.ACTIVATED)
        )
        for future_license in future_licenses:
            original_license = future_license.renewed_from

            self.assertEqual(future_license.status, original_license.status)
            self.assertEqual(future_license.user_email, original_license.user_email)
            self.assertEqual(future_license.lms_user_id, original_license.lms_user_id)
            if original_license.status == constants.ACTIVATED:
                self.assertEqual(future_license.activation_date, expected_activation_datetime)
            self.assertEqual(future_license.assigned_date, NOW)

    def test_renewal_processed_with_no_existing_future_plan(self):
        prior_plan = SubscriptionPlanFactory()
        original_activated_licenses = [
            LicenseFactory.create(
                subscription_plan=prior_plan,
                status=constants.ACTIVATED,
                user_email='activated_user_{}@example.com'.format(i)
            ) for i in range(5)
        ]
        original_assigned_licenses = [
            LicenseFactory.create(
                subscription_plan=prior_plan,
                status=constants.ASSIGNED,
                user_email='assigned_user_{}@example.com'.format(i)
            ) for i in range(5)
        ]
        original_licenses = original_activated_licenses + original_assigned_licenses

        renewal = SubscriptionPlanRenewalFactory(
            prior_subscription_plan=prior_plan,
            number_of_licenses=10,
            license_types_to_copy=constants.LicenseTypesToRenew.ASSIGNED_AND_ACTIVATED
        )

        with freezegun.freeze_time(NOW):
            api.renew_subscription(renewal)

        renewal.refresh_from_db()
        original_plan = renewal.prior_subscription_plan
        future_plan = renewal.renewed_subscription_plan
        self.assertTrue(renewal.processed)
        self.assertEqual(renewal.processed_datetime, NOW)
        self.assertEqual(original_plan.product_id, future_plan.product_id)
        self.assertEqual(future_plan.num_licenses, renewal.number_of_licenses)
        self._assert_all_licenses_renewed(future_plan)

    def test_renewal_processed_with_existing_future_plan(self):
        prior_plan = SubscriptionPlanFactory()
        original_licenses = [
            LicenseFactory.create(
                subscription_plan=prior_plan,
                status=constants.ACTIVATED,
                user_email='activated_user_{}@example.com'.format(i)
            ) for i in range(5)
        ]

        # create some revoked original licenses that should not be renewed
        LicenseFactory.create_batch(
            67,
            subscription_plan=prior_plan,
            status=constants.REVOKED,
        )

        future_plan = SubscriptionPlanFactory()
        LicenseFactory.create_batch(
            10,
            subscription_plan=future_plan,
            status=constants.UNASSIGNED,
        )
        renewal = SubscriptionPlanRenewalFactory(
            prior_subscription_plan=prior_plan,
            renewed_subscription_plan=future_plan,
            number_of_licenses=10,

        )

        with freezegun.freeze_time(NOW):
            api.renew_subscription(renewal)

        future_plan.refresh_from_db()
        self.assertTrue(renewal.processed)
        self.assertEqual(renewal.processed_datetime, NOW)
        self.assertEqual(future_plan.num_licenses, renewal.number_of_licenses)
        self._assert_all_licenses_renewed(future_plan)

    @ddt.data(
        True,
        False,
        None
    )
    def test_renewal_future_plan_auto_applies_licenses(self, should_auto_apply_licenses):
        customer_agreement = CustomerAgreementFactory.create()
        prior_plan = SubscriptionPlanFactory(
            customer_agreement=customer_agreement,
            should_auto_apply_licenses=should_auto_apply_licenses
        )
        renewal = SubscriptionPlanRenewalFactory(
            prior_subscription_plan=prior_plan,
            number_of_licenses=1,
            license_types_to_copy=constants.LicenseTypesToRenew.ASSIGNED_AND_ACTIVATED,
            effective_date=NOW
        )

        with freezegun.freeze_time(NOW):
            api.renew_subscription(renewal)

        renewal.refresh_from_db()
        future_plan = renewal.renewed_subscription_plan

        if should_auto_apply_licenses:
            self.assertTrue(future_plan.should_auto_apply_licenses)
            self.assertEqual(customer_agreement.auto_applicable_subscription, future_plan)
        else:
            assert future_plan.should_auto_apply_licenses is None
            assert customer_agreement.auto_applicable_subscription is None

    def test_renewal_disable_auto_apply_licenses(self):
        customer_agreement = CustomerAgreementFactory.create()
        prior_plan = SubscriptionPlanFactory(
            customer_agreement=customer_agreement,
            should_auto_apply_licenses=True
        )
        renewal = SubscriptionPlanRenewalFactory(
            prior_subscription_plan=prior_plan,
            number_of_licenses=1,
            license_types_to_copy=constants.LicenseTypesToRenew.ASSIGNED_AND_ACTIVATED,
            disable_auto_apply_licenses=True
        )

        with freezegun.freeze_time(NOW):
            api.renew_subscription(renewal)

        future_plan = renewal.renewed_subscription_plan
        self.assertFalse(future_plan.should_auto_apply_licenses)
        assert customer_agreement.auto_applicable_subscription is None

    @mock.patch('license_manager.apps.subscriptions.event_utils.track_event')
    def test_renewal_processed_segment_events(self, mock_track_event):
        prior_plan = SubscriptionPlanFactory()
        [LicenseFactory.create(
            subscription_plan=prior_plan,
            status=constants.ACTIVATED,
            user_email='activated_user_{}@example.com'
        )]

        renewal = SubscriptionPlanRenewalFactory(
            prior_subscription_plan=prior_plan,
            number_of_licenses=1,
            license_types_to_copy=constants.LicenseTypesToRenew.ASSIGNED_AND_ACTIVATED
        )
        api.renew_subscription(renewal)
        assert mock_track_event.call_count == 2
        assert (mock_track_event.call_args_list[0].args[1] == constants.SegmentEvents.LICENSE_CREATED)
        assert (mock_track_event.call_args_list[1].args[1] == constants.SegmentEvents.LICENSE_RENEWED)
        self.assertFalse(mock_track_event.call_args_list[1].args[2]['is_auto_renewed'])

    @mock.patch('license_manager.apps.subscriptions.event_utils.track_event')
    def test_renewal_processed_segment_events_is_auto_renewed(self, mock_track_event):
        prior_plan = SubscriptionPlanFactory()
        [LicenseFactory.create(
            subscription_plan=prior_plan,
            status=constants.ACTIVATED,
            user_email='activated_user_{}@example.com'
        )]

        renewal = SubscriptionPlanRenewalFactory(
            prior_subscription_plan=prior_plan,
            number_of_licenses=1,
            license_types_to_copy=constants.LicenseTypesToRenew.ASSIGNED_AND_ACTIVATED
        )
        api.renew_subscription(renewal, is_auto_renewed=True)
        assert mock_track_event.call_count == 2
        assert (mock_track_event.call_args_list[0].args[1] == constants.SegmentEvents.LICENSE_CREATED)
        assert (mock_track_event.call_args_list[1].args[1] == constants.SegmentEvents.LICENSE_RENEWED)
        self.assertTrue(mock_track_event.call_args_list[1].args[2]['is_auto_renewed'])


@ddt.ddt
class RevocationTests(TestCase):
    """
    Tests for the ``revoke_license()`` function.
    """
    @ddt.data(
        {'revoke_max_percentage': 0, 'number_licenses_to_create': 1},
        {'revoke_max_percentage': 1.0, 'number_licenses_to_create': 7},
        {'revoke_max_percentage': 0.2, 'number_licenses_to_create': 10},
        {'revoke_max_percentage': 0.5, 'number_licenses_to_create': 13},
        {'revoke_max_percentage': 0.74, 'number_licenses_to_create': 15},
    )
    @ddt.unpack
    def test_revocation_limit_reached_raises_error(
        self,
        revoke_max_percentage,
        number_licenses_to_create,
    ):
        subscription_plan = SubscriptionPlanFactory.create(
            is_revocation_cap_enabled=True,
            revoke_max_percentage=revoke_max_percentage,
            # SubscriptionPlan.num_revocations_remaining defines the absolute revocation cap
            # as:
            #
            # revocations_remaining =
            #    ceil(num_licenses * revoke_max_percentage) - num_revocations_applied
            #
            # So given the revoke max percentage and number of licenses to create,
            # we can derive the number of revocations previously applied in the plan
            # needed in order to raise an exception the "next time" we attempt a revocation
            # by setting revocations_remaining to 0 and solving for num_revocations_applied:
            #
            # 0 = ceil(num_licenses * revoke_max_percent) - num_revocations_applied
            # ==>
            # num_revocations_applied = ceil(num_licenses * revoke_max_percent)
            #
            # (the "next time we revoke" being the call to revoke_license() below).
            num_revocations_applied=ceil(revoke_max_percentage * number_licenses_to_create),
        )
        original_licenses = LicenseFactory.create_batch(
            number_licenses_to_create,
            status=constants.ACTIVATED,
            subscription_plan=subscription_plan,
        )

        for original_license in original_licenses:
            with self.assertRaisesRegex(exceptions.LicenseRevocationError, 'limit has been reached'):
                api.revoke_license(original_license)

            original_license.refresh_from_db()
            self.assertEqual(original_license.status, constants.ACTIVATED)

    @ddt.data(
        constants.REVOKED,
        constants.UNASSIGNED,
    )
    def test_cannot_revoke_license_if_not_assigned_or_activated(
            self, license_status
    ):
        subscription_plan = SubscriptionPlanFactory.create(
            is_revocation_cap_enabled=False,
        )
        original_license = LicenseFactory.create(
            status=license_status,
            subscription_plan=subscription_plan,
        )

        expected_msg = 'status of {} cannot be revoked'.format(license_status)
        with self.assertRaisesRegex(exceptions.LicenseRevocationError, expected_msg):
            api.revoke_license(original_license)

        original_license.refresh_from_db()
        self.assertEqual(original_license.status, license_status)

    @ddt.data(True, False)
    def test_activated_license_is_revoked(
        self, is_revocation_cap_enabled,
    ):
        agreement = CustomerAgreementFactory.create(
            enterprise_customer_uuid=uuid.UUID('00000000-1111-2222-3333-444444444444'),
        )
        subscription_plan = SubscriptionPlanFactory.create(
            customer_agreement=agreement,
            is_revocation_cap_enabled=is_revocation_cap_enabled,
            num_revocations_applied=0,
            revoke_max_percentage=100,
        )
        original_license = LicenseFactory.create(
            status=constants.ACTIVATED,
            subscription_plan=subscription_plan,
            lms_user_id=123,
        )

        with freezegun.freeze_time(NOW):
            api.revoke_license(original_license)

        original_license.refresh_from_db()
        self.assertEqual(original_license.status, constants.REVOKED)
        self.assertEqual(original_license.revoked_date, NOW)

        # There should now be 1 unassigned license
        self.assertEqual(subscription_plan.unassigned_licenses.count(), 1)


class SubscriptionFreezeTests(TestCase):
    """
    Tests for the freezing of a Subscription Plan where all unassigned licenses are deleted.
    """
    def test_cannot_freeze_plan_with_freezing_unsupported(self):
        subscription_plan = SubscriptionPlanFactory()

        expected_message = 'The plan does not support freezing unused licenses.'
        with self.assertRaisesRegex(exceptions.UnprocessableSubscriptionPlanFreezeError, expected_message):
            api.delete_unused_licenses_post_freeze(subscription_plan)

    def test_delete_unassigned_licenses_post_freeze(self):
        subscription_plan = SubscriptionPlanFactory(can_freeze_unused_licenses=True)
        LicenseFactory.create_batch(
            5,
            subscription_plan=subscription_plan,
            status=constants.UNASSIGNED,
        )
        LicenseFactory.create_batch(
            2,
            subscription_plan=subscription_plan,
            status=constants.ASSIGNED,
        )
        LicenseFactory.create_batch(
            1,
            subscription_plan=subscription_plan,
            status=constants.ACTIVATED,
        )

        with freezegun.freeze_time(NOW):
            api.delete_unused_licenses_post_freeze(subscription_plan)

        assert subscription_plan.unassigned_licenses.count() == 0
        assert subscription_plan.assigned_licenses.count() == 2
        assert subscription_plan.activated_licenses.count() == 1

        assert subscription_plan.last_freeze_timestamp == NOW


class CustomerAgreementSyncTests(TestCase):
    """
    Tests for syncing data from the ``EnterpriseApiClient`` to the
    CustomerAgreement record (e.g., the enterprise customer slug).
    """
    @mock.patch('license_manager.apps.subscriptions.api.EnterpriseApiClient', autospec=True)
    def test_sync_slug(self, mock_client):
        new_slug = 'new-slug'
        new_name = 'New Name'
        agreement = CustomerAgreementFactory()
        agreement.enterprise_customer_slug = 'original-slug'
        agreement.enterprise_customer_name = 'Original Name'
        client = mock_client.return_value
        client.get_enterprise_customer_data.return_value = {
            'slug': new_slug,
            'name': new_name,
        }

        api.sync_agreement_with_enterprise_customer(customer_agreement=agreement)

        self.assertTrue(mock_client.called)
        client.get_enterprise_customer_data.assert_called_once_with(
            agreement.enterprise_customer_uuid
        )
        self.assertEqual(new_slug, agreement.enterprise_customer_slug)
        self.assertEqual(new_name, agreement.enterprise_customer_name)

    @mock.patch('license_manager.apps.subscriptions.api.EnterpriseApiClient', autospec=True)
    def test_save_without_slug_http_error(self, mock_client):
        original_slug = 'original-slug'
        original_name = 'Original Name'
        agreement = CustomerAgreementFactory()
        agreement.enterprise_customer_slug = original_slug
        agreement.enterprise_customer_name = original_name
        client = mock_client.return_value
        client.get_enterprise_customer_data.side_effect = HTTPError('some error')

        with self.assertRaisesRegex(exceptions.CustomerAgreementError, 'some error'):
            api.sync_agreement_with_enterprise_customer(customer_agreement=agreement)

        self.assertTrue(mock_client.called)
        client.get_enterprise_customer_data.assert_called_once_with(
            agreement.enterprise_customer_uuid
        )
        self.assertEqual(agreement.enterprise_customer_slug, original_slug)
        self.assertEqual(agreement.enterprise_customer_name, original_name)


@ddt.ddt
class ToggleAutoApplyLicensesTests(TestCase):
    """
    Tests for toggling auto apply licenses on a subscription plan.
    """

    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()

        customer_agreement = CustomerAgreementFactory()
        subscription_plan_1 = SubscriptionPlanFactory(customer_agreement=customer_agreement)
        subscription_plan_2 = SubscriptionPlanFactory(customer_agreement=customer_agreement)

        cls.customer_agreement = customer_agreement
        cls.subscription_plan_1 = subscription_plan_1
        cls.subscription_plan_2 = subscription_plan_2

    def tearDown(self):
        super().tearDown()
        CustomerAgreement.objects.all().delete()
        SubscriptionPlan.objects.all().delete()

    def test_toggle_auto_apply_licenses_zero_state(self):
        api.toggle_auto_apply_licenses(
            customer_agreement_uuid=self.customer_agreement.uuid,
            subscription_uuid=self.subscription_plan_1.uuid
        )
        self.subscription_plan_1.refresh_from_db()
        self.assertTrue(self.subscription_plan_1.should_auto_apply_licenses)

    @ddt.data(None, '')
    def test_toggle_auto_apply_licenses_no_subscription_uuid(self, subscription_uuid):
        self.subscription_plan_1.should_auto_apply_licenses = True
        self.subscription_plan_1.save()
        api.toggle_auto_apply_licenses(
            customer_agreement_uuid=self.customer_agreement.uuid,
            subscription_uuid=subscription_uuid
        )
        self.assertEqual(len(SubscriptionPlan.objects.filter(should_auto_apply_licenses=True)), 0)

    def test_toggle_auto_apply_licenses_current_plan_exists(self):
        self.subscription_plan_1.should_auto_apply_licenses = True
        self.subscription_plan_1.save()

        self.assertTrue(self.subscription_plan_1.should_auto_apply_licenses)
        self.assertFalse(self.subscription_plan_2.should_auto_apply_licenses)
        api.toggle_auto_apply_licenses(
            customer_agreement_uuid=self.customer_agreement.uuid,
            subscription_uuid=self.subscription_plan_2.uuid
        )

        self.subscription_plan_1.refresh_from_db()
        self.subscription_plan_2.refresh_from_db()

        self.assertFalse(self.subscription_plan_1.should_auto_apply_licenses)
        self.assertTrue(self.subscription_plan_2.should_auto_apply_licenses)
