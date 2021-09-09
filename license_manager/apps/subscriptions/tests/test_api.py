import uuid
from datetime import timedelta
from math import ceil
from unittest import mock

import ddt
import freezegun
from django.test import TestCase
from requests.exceptions import HTTPError

from license_manager.apps.subscriptions import api, constants, exceptions, utils
from license_manager.apps.subscriptions.tests.factories import (
    CustomerAgreementFactory,
    LicenseFactory,
    SubscriptionPlanFactory,
    SubscriptionPlanRenewalFactory,
)


NOW = utils.localized_utcnow()


class PostRenewalExpirationTests(TestCase):
    """
    Tests for the expiration of subscription plans
    that have been renewed.
    """
    def test_no_action_for_previously_processed_expiration(self):
        plan = SubscriptionPlanFactory(
            expiration_date=utils.localized_utcnow() - timedelta(days=30),
            expiration_processed=True,
        )

        expected_message = "The plan's expiration is already marked as processed."
        with self.assertRaisesRegex(exceptions.UnprocessableSubscriptionPlanExpirationError, expected_message):
            api.expire_plan_post_renewal(plan)

    def test_no_action_for_unexpired_subscription(self):
        unexpired_plan = SubscriptionPlanFactory(
            expiration_date=utils.localized_utcnow() + timedelta(days=30),
            expiration_processed=False,
        )

        expected_message = "The plan's expiration date is in the future."
        with self.assertRaisesRegex(exceptions.UnprocessableSubscriptionPlanExpirationError, expected_message):
            api.expire_plan_post_renewal(unexpired_plan)

    def test_no_action_when_no_associated_renewal(self):
        expired_plan = SubscriptionPlanFactory(
            expiration_date=utils.localized_utcnow() - timedelta(days=30),
            expiration_processed=False,
        )
        LicenseFactory.create_batch(
            5,
            subscription_plan=expired_plan,
            status=constants.ASSIGNED,
        )

        expected_message = "The plan has no associated renewal record."
        with self.assertRaisesRegex(exceptions.UnprocessableSubscriptionPlanExpirationError, expected_message):
            api.expire_plan_post_renewal(expired_plan)

    def test_no_action_when_renewal_is_not_processed(self):
        expired_plan = SubscriptionPlanFactory(
            expiration_date=utils.localized_utcnow() - timedelta(days=30),
            expiration_processed=False,
        )
        LicenseFactory.create_batch(
            5,
            subscription_plan=expired_plan,
            status=constants.ASSIGNED,
        )
        SubscriptionPlanRenewalFactory.create(
            number_of_licenses=5,
            prior_subscription_plan=expired_plan,
            processed=False,
        )

        expected_message = "The plan's renewal has not been processed."
        with self.assertRaisesRegex(exceptions.UnprocessableSubscriptionPlanExpirationError, expected_message):
            api.expire_plan_post_renewal(expired_plan)

    def test_expiration_processed_and_licenses_transferred(self):
        expired_plan = SubscriptionPlanFactory(
            expiration_date=utils.localized_utcnow() - timedelta(days=30),
            expiration_processed=False,
        )
        LicenseFactory.create_batch(
            5,
            subscription_plan=expired_plan,
            status=constants.ASSIGNED,
        )
        SubscriptionPlanRenewalFactory.create(
            number_of_licenses=5,
            prior_subscription_plan=expired_plan,
            processed=True,
        )

        api.expire_plan_post_renewal(expired_plan)

        self.assertTrue(expired_plan.expiration_processed)


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
        future_plan = renewal.renewed_subscription_plan
        self.assertTrue(renewal.processed)
        self.assertEqual(renewal.processed_datetime, NOW)
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

    @mock.patch('license_manager.apps.subscriptions.event_utils.track_event')
    def test_renewal_processed_segment_events(self, mock_track_event):
        prior_plan = SubscriptionPlanFactory()
        original_activated_licenses = [LicenseFactory.create(
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
        assert mock_track_event.call_count == len(original_activated_licenses)
        self.assertFalse(mock_track_event.call_args_list[0].args[2]['is_auto_renewed'])

    @mock.patch('license_manager.apps.subscriptions.event_utils.track_event')
    def test_renewal_processed_segment_events_is_auto_renewed(self, mock_track_event):
        prior_plan = SubscriptionPlanFactory()
        original_activated_licenses = [LicenseFactory.create(
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
        assert mock_track_event.call_count == len(original_activated_licenses)
        self.assertTrue(mock_track_event.call_args_list[0].args[2]['is_auto_renewed'])


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
    @mock.patch('license_manager.apps.subscriptions.api.revoke_course_enrollments_for_user_task.delay')
    @mock.patch('license_manager.apps.subscriptions.api.send_revocation_cap_notification_email_task.delay')
    def test_revocation_limit_reached_raises_error(
        self,
        mock_cap_email_delay,
        mock_revoke_enrollments_delay,
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
            self.assertFalse(mock_cap_email_delay.called)
            self.assertFalse(mock_revoke_enrollments_delay.called)

    @ddt.data(
        constants.REVOKED,
        constants.UNASSIGNED,
    )
    @mock.patch('license_manager.apps.subscriptions.api.revoke_course_enrollments_for_user_task.delay')
    @mock.patch('license_manager.apps.subscriptions.api.send_revocation_cap_notification_email_task.delay')
    def test_cannot_revoke_license_if_not_assigned_or_activated(
            self, license_status, mock_cap_email_delay, mock_revoke_enrollments_delay
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
        self.assertFalse(mock_cap_email_delay.called)
        self.assertFalse(mock_revoke_enrollments_delay.called)

    @ddt.data(True, False)
    @mock.patch('license_manager.apps.subscriptions.api.revoke_course_enrollments_for_user_task.delay')
    @mock.patch('license_manager.apps.subscriptions.api.send_revocation_cap_notification_email_task.delay')
    def test_activated_license_is_revoked(
        self, should_send_revocation_cap_email, mock_cap_email_delay, mock_revoke_enrollments_delay
    ):
        agreement = CustomerAgreementFactory.create(
            enterprise_customer_uuid=uuid.UUID('00000000-1111-2222-3333-444444444444'),
        )
        subscription_plan = SubscriptionPlanFactory.create(
            customer_agreement=agreement,
            is_revocation_cap_enabled=should_send_revocation_cap_email,
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

        if not should_send_revocation_cap_email:
            self.assertFalse(mock_cap_email_delay.called)
        else:
            mock_cap_email_delay.assert_called_once_with(
                subscription_uuid=subscription_plan.uuid,
            )

        mock_revoke_enrollments_delay.assert_called_once_with(
            user_id=original_license.lms_user_id,
            enterprise_id=str(subscription_plan.enterprise_customer_uuid),
        )
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
        agreement = CustomerAgreementFactory()
        agreement.enterprise_customer_slug = 'original-slug'
        client = mock_client.return_value
        client.get_enterprise_customer_data.return_value = {
            'slug': new_slug,
        }

        api.sync_agreement_with_enterprise_slug(customer_agreement=agreement)

        self.assertTrue(mock_client.called)
        client.get_enterprise_customer_data.assert_called_once_with(
            agreement.enterprise_customer_uuid
        )
        self.assertEqual(new_slug, agreement.enterprise_customer_slug)

    @mock.patch('license_manager.apps.subscriptions.api.EnterpriseApiClient', autospec=True)
    def test_save_without_slug_http_error(self, mock_client):
        original_slug = 'original-slug'
        agreement = CustomerAgreementFactory()
        agreement.enterprise_customer_slug = 'original-slug'
        client = mock_client.return_value
        client.get_enterprise_customer_data.side_effect = HTTPError('some error')

        with self.assertRaisesRegex(exceptions.CustomerAgreementError, 'some error'):
            api.sync_agreement_with_enterprise_slug(customer_agreement=agreement)

        self.assertTrue(mock_client.called)
        client.get_enterprise_customer_data.assert_called_once_with(
            agreement.enterprise_customer_uuid
        )
        self.assertEqual(agreement.enterprise_customer_slug, original_slug)
