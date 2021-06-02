from datetime import datetime, timedelta
from unittest import mock

import ddt
import freezegun
from django.test import TestCase
from pytz import UTC

from license_manager.apps.subscriptions import api, constants, utils
from license_manager.apps.subscriptions.tests.factories import (
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
        with self.assertRaisesRegex(api.UnprocessableSubscriptionPlanExpirationError, expected_message):
            api.expire_plan_post_renewal(plan)

    def test_no_action_for_unexpired_subscription(self):
        unexpired_plan = SubscriptionPlanFactory(
            expiration_date=utils.localized_utcnow() + timedelta(days=30),
            expiration_processed=False,
        )

        expected_message = "The plan's expiration date is in the future."
        with self.assertRaisesRegex(api.UnprocessableSubscriptionPlanExpirationError, expected_message):
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
        with self.assertRaisesRegex(api.UnprocessableSubscriptionPlanExpirationError, expected_message):
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
        with self.assertRaisesRegex(api.UnprocessableSubscriptionPlanExpirationError, expected_message):
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
        with self.assertRaisesRegex(api.RenewalProcessingError, expected_message):
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
        with self.assertRaisesRegex(api.RenewalProcessingError, expected_message):
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
        with self.assertRaisesRegex(api.RenewalProcessingError, expected_message):
            api.renew_subscription(renewal)

    def _assert_all_licenses_renewed(self, future_plan):
        """
        Helper to assert that future license fields are updated with expected values.
        """
        expected_activation_datetime = utils.localized_datetime_from_date(future_plan.start_date)

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
