from unittest import TestCase, mock
from uuid import uuid4

import ddt
import freezegun
from pytest import mark

from license_manager.apps.api.api import execute_post_revocation_tasks
from license_manager.apps.subscriptions import api, constants, utils
from license_manager.apps.subscriptions.tests.factories import (
    CustomerAgreementFactory,
    LicenseFactory,
    SubscriptionPlanFactory,
)


NOW = utils.localized_utcnow()


@ddt.ddt
@mark.django_db
class TrackLicenseChangesTests(TestCase):
    """
    Tests for track_license_changes_task.
    """

    @ddt.data(
        {'original_status': constants.ACTIVATED, 'revoke_max_percentage': 200},
        {'original_status': constants.ACTIVATED, 'revoke_max_percentage': 100},
        {'original_status': constants.ASSIGNED, 'revoke_max_percentage': 100}
    )
    @ddt.unpack
    @mock.patch('license_manager.apps.api.api.tasks.revoke_course_enrollments_for_user_task.delay')
    @mock.patch('license_manager.apps.api.api.tasks.send_revocation_cap_notification_email_task.delay')
    def test_execute_post_revocation_tasks(
        self,
        mock_cap_email_delay,
        mock_revoke_enrollments_delay,
        original_status,
        revoke_max_percentage
    ):
        agreement = CustomerAgreementFactory.create(
            enterprise_customer_uuid=uuid4(),
        )

        subscription_plan = SubscriptionPlanFactory.create(
            customer_agreement=agreement,
            is_revocation_cap_enabled=True,
            num_revocations_applied=0,
            revoke_max_percentage=revoke_max_percentage,
        )

        original_license = LicenseFactory.create(
            status=original_status,
            subscription_plan=subscription_plan,
            lms_user_id=123,
        )

        with freezegun.freeze_time(NOW):
            revocation_result = api.revoke_license(original_license)
            execute_post_revocation_tasks(**revocation_result)

        is_license_revoked = original_status == constants.ACTIVATED
        revoke_limit_reached = is_license_revoked and revoke_max_percentage <= 100

        self.assertEqual(mock_revoke_enrollments_delay.called, is_license_revoked)
        self.assertEqual(mock_cap_email_delay.called, revoke_limit_reached)
