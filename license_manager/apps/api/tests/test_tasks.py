"""
Tests for the license-manager API celery tasks
"""
from datetime import timedelta
from smtplib import SMTPException
from unittest import mock
from uuid import uuid4

import ddt
import freezegun
import pytest
from django.conf import settings
from django.test import TestCase
from django.test.utils import override_settings
from freezegun import freeze_time
from requests import models

from license_manager.apps.api import tasks
from license_manager.apps.api.tests.factories import BulkEnrollmentJobFactory
from license_manager.apps.subscriptions import constants
from license_manager.apps.subscriptions.constants import (
    ASSIGNED,
    WEEKLY_UTILIZATION_EMAIL_INTERLUDE,
    NotificationChoices,
)
from license_manager.apps.subscriptions.exceptions import LicenseRevocationError
from license_manager.apps.subscriptions.models import (
    CustomerAgreement,
    License,
    Notification,
    SubscriptionPlan,
)
from license_manager.apps.subscriptions.tests.factories import (
    CustomerAgreementFactory,
    LicenseFactory,
    SubscriptionPlanFactory,
    UserFactory,
)
from license_manager.apps.subscriptions.tests.utils import (
    assert_date_fields_correct,
    make_test_email_data,
)
from license_manager.apps.subscriptions.utils import localized_utcnow


@ddt.ddt
class EmailTaskTests(TestCase):
    """
    Tests for activation_email_task and send_onboarding_email_task
    """
    def setUp(self):
        super().setUp()
        test_email_data = make_test_email_data()
        self.user_email = 'test_email@example.com'
        self.subscription_plan = test_email_data['subscription_plan']
        self.custom_template_text = test_email_data['custom_template_text']
        self.email_recipient_list = test_email_data['email_recipient_list']
        self.assigned_licenses = self.subscription_plan.licenses.filter(status=constants.ASSIGNED).order_by('uuid')
        self.enterprise_uuid = uuid4()
        self.enterprise_slug = 'mock-enterprise'
        self.enterprise_name = 'Mock Enterprise'
        self.enterprise_sender_alias = 'Mock Enterprise Alias'
        self.reply_to_email = 'edx@example.com'
        self.subscription_plan_type = self.subscription_plan.product.plan_type_id

    @mock.patch('license_manager.apps.api.tasks.EnterpriseApiClient', return_value=mock.MagicMock())
    @mock.patch('license_manager.apps.api.tasks.send_activation_emails')
    def test_activation_task(self, mock_send_emails, mock_enterprise_client):
        """
        Assert activation_task is called with the correct arguments
        """
        mock_enterprise_client().get_enterprise_customer_data.return_value = {
            'slug': self.enterprise_slug,
            'name': self.enterprise_name,
            'sender_alias': self.enterprise_sender_alias,
            'reply_to': self.reply_to_email,
        }

        tasks.activation_email_task(
            self.custom_template_text,
            self.email_recipient_list,
            self.subscription_plan.uuid,
        )

        send_email_args, _ = mock_send_emails.call_args
        self._verify_mock_send_email_arguments(send_email_args)
        mock_enterprise_client().get_enterprise_customer_data.assert_called_with(
            self.subscription_plan.enterprise_customer_uuid
        )

    @mock.patch('license_manager.apps.api.tasks.logger', return_value=mock.MagicMock())
    @mock.patch('license_manager.apps.api.tasks.send_activation_emails', side_effect=SMTPException)
    @mock.patch('license_manager.apps.api.tasks.EnterpriseApiClient', return_value=mock.MagicMock())
    def test_activation_task_send_email_failure_logged(self, mock_enterprise_client, mock_send_emails, mock_logger):
        """
        Tests that when sending the activate email fails, an error gets logged
        """
        mock_enterprise_client().get_enterprise_customer_data.return_value = {
            'slug': self.enterprise_slug,
            'name': self.enterprise_name,
            'sender_alias': self.enterprise_sender_alias,
            'reply_to': self.reply_to_email,
        }

        with mock_send_emails:
            tasks.activation_email_task(
                self.custom_template_text,
                self.email_recipient_list,
                self.subscription_plan.uuid
            )

        mock_logger.error.assert_called_once()

    @mock.patch('license_manager.apps.api.tasks.send_activation_emails')
    @mock.patch('license_manager.apps.api.tasks.EnterpriseApiClient', return_value=mock.MagicMock())
    def test_send_reminder_email_task(self, mock_enterprise_client, mock_send_emails):
        """
        Assert send_reminder_email_task is called with the correct arguments
        """
        mock_enterprise_client().get_enterprise_customer_data.return_value = {
            'slug': self.enterprise_slug,
            'name': self.enterprise_name,
            'sender_alias': self.enterprise_sender_alias,
            'reply_to': self.reply_to_email,
        }
        with freeze_time(localized_utcnow()):
            tasks.send_reminder_email_task(
                self.custom_template_text,
                self.email_recipient_list,
                self.subscription_plan.uuid
            )

            send_email_args, _ = mock_send_emails.call_args
            self._verify_mock_send_email_arguments(send_email_args)
            mock_enterprise_client().get_enterprise_customer_data.assert_called_with(
                self.subscription_plan.enterprise_customer_uuid
            )
            # Verify the 'last_remind_date' of all licenses have been updated
            assert_date_fields_correct(send_email_args[1], ['last_remind_date'], True)

    @mock.patch('license_manager.apps.api.tasks.send_activation_emails', side_effect=SMTPException)
    @mock.patch('license_manager.apps.api.tasks.EnterpriseApiClient', return_value=mock.MagicMock())
    def test_send_reminder_email_failure_no_remind_date_update(self, mock_enterprise_client, mock_send_emails):
        """
        Tests that when sending the remind email fails, last_remind_date is not updated
        """
        mock_enterprise_client().get_enterprise_customer_data.return_value = {
            'slug': self.enterprise_slug,
            'name': self.enterprise_name,
            'sender_alias': self.enterprise_sender_alias,
            'reply_to': self.reply_to_email,
        }
        with mock_send_emails:
            tasks.send_reminder_email_task(
                self.custom_template_text,
                self.email_recipient_list,
                self.subscription_plan.uuid
            )
            send_email_args, _ = mock_send_emails.call_args
            assert_date_fields_correct(send_email_args[1], ['last_remind_date'], False)

    def _verify_mock_send_email_arguments(self, send_email_args):
        """
        Verifies that the arguments passed into send_activation_emails is correct
        """
        (
            actual_template_text,
            actual_licenses,
            actual_enterprise_slug,
            actual_enterprise_name,
            actual_enterprise_sender_alias,
            actual_enterprise_reply_to_email,
            actual_subscription_plan_type,
        ) = send_email_args[:7]

        assert list(self.assigned_licenses) == list(actual_licenses)
        assert self.custom_template_text == actual_template_text
        assert self.enterprise_slug == actual_enterprise_slug
        assert self.enterprise_name == actual_enterprise_name
        assert self.enterprise_sender_alias == actual_enterprise_sender_alias
        assert self.reply_to_email == actual_enterprise_reply_to_email
        assert self.subscription_plan_type == actual_subscription_plan_type

    @mock.patch('license_manager.apps.api.tasks.send_onboarding_email', return_value=mock.MagicMock())
    def test_onboarding_email_task(self, mock_send_onboarding_email):
        """
        Tests that the onboarding email task sends the email
        """
        tasks.send_onboarding_email_task(self.enterprise_uuid, self.user_email, self.subscription_plan_type)
        mock_send_onboarding_email.assert_called_with(
            self.enterprise_uuid,
            self.user_email,
            self.subscription_plan_type,
        )

    @override_settings(AUTOAPPLY_WITH_LEARNER_PORTAL_CAMPAIGN='LP-campaign-id')
    @ddt.data(
        {
            'lp_search': True,
            'identity_provider': uuid4(),
        },
        {
            'lp_search': False,
            'identity_provider': uuid4(),
        },
        {
            'lp_search': True,
            'identity_provider': None,
        },
        {
            'lp_search': False,
            'identity_provider': None,
        },
    )
    @ddt.unpack
    @mock.patch('license_manager.apps.api.tasks.BrazeApiClient', return_value=mock.MagicMock())
    @mock.patch('license_manager.apps.api.tasks.EnterpriseApiClient', return_value=mock.MagicMock())
    def test_auto_applied_license_onboard_email(self, mock_enterprise_client, mock_braze_client, lp_search, identity_provider):
        """
        Tests braze API is called when everything works as expected.
        """
        mock_enterprise_client().get_enterprise_customer_data.return_value = {
            'slug': self.enterprise_slug,
            'name': self.enterprise_name,
            'sender_alias': self.enterprise_sender_alias,
            'enable_integrated_customer_learner_portal_search': lp_search,
            'identity_provider': identity_provider,
        }

        tasks.send_auto_applied_license_email_task(self.enterprise_uuid, self.user_email)

        expected_trigger_properties = {
            'enterprise_customer_slug': self.enterprise_slug,
            'enterprise_customer_name': self.enterprise_name,
        }

        if identity_provider and lp_search is False:
            expected_campaign_id = ''  # Empty because setting isn't set in tests
        else:
            expected_campaign_id = 'LP-campaign-id'

        mock_braze_client().send_campaign_message.assert_called_with(
            expected_campaign_id,
            emails=[self.user_email],
            trigger_properties=expected_trigger_properties,
        )

    @mock.patch('license_manager.apps.api.tasks.logger', return_value=mock.MagicMock())
    @mock.patch('license_manager.apps.api.tasks.BrazeApiClient', return_value=mock.MagicMock())
    @mock.patch('license_manager.apps.api.tasks.EnterpriseApiClient', side_effect=Exception)
    def test_auto_applied_license_onboard_email_ent_client_error(self, mock_enterprise_client, mock_braze_client, mock_logger):
        """
        Tests braze API is not called if enterprise client errors.
        """
        tasks.send_auto_applied_license_email_task(self.enterprise_uuid, self.user_email)

        mock_braze_client().send_campaign_message.assert_not_called()
        mock_logger.error.assert_called_once()

    @mock.patch('license_manager.apps.api.tasks.logger', return_value=mock.MagicMock())
    @mock.patch('license_manager.apps.api.tasks.BrazeApiClient', side_effect=Exception)
    @mock.patch('license_manager.apps.api.tasks.EnterpriseApiClient', return_value=mock.MagicMock())
    def test_auto_applied_license_onboard_email_braze_client_error(self, mock_enterprise_client, mock_braze_client, mock_logger):
        """
        Tests error logged if brazy client errors.
        """
        mock_enterprise_client().get_enterprise_customer_data.return_value = {
            'slug': self.enterprise_slug,
            'name': self.enterprise_name,
            'sender_alias': self.enterprise_sender_alias,
            'enable_integrated_customer_learner_portal_search': True,
            'identity-provider': uuid4(),
        }

        tasks.send_auto_applied_license_email_task(self.enterprise_uuid, self.user_email)

        mock_logger.error.assert_called_once()


class RevokeAllLicensesTaskTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()

        subscription_plan = SubscriptionPlanFactory()
        unassigned_license = LicenseFactory.create(status=constants.UNASSIGNED, subscription_plan=subscription_plan)
        assigned_license = LicenseFactory.create(status=constants.ASSIGNED, subscription_plan=subscription_plan)
        activated_license = LicenseFactory.create(status=constants.ACTIVATED, subscription_plan=subscription_plan)

        cls.subscription_plan = subscription_plan
        cls.unassigned_license = unassigned_license
        cls.assigned_license = assigned_license
        cls.activated_license = activated_license

    def tearDown(self):
        """
        Deletes all licenses, and subscription after each test method is run.
        """
        super().tearDown()
        License.objects.all().delete()
        SubscriptionPlan.objects.all().delete()

    @mock.patch('license_manager.apps.subscriptions.api.execute_post_revocation_tasks')
    @mock.patch('license_manager.apps.subscriptions.api.revoke_license')
    def test_revoke_all_licenses_task(self, mock_revoke_license, mock_execute_post_revocation_tasks):
        """
        Verify that revoke_license and execute_post_revocation_tasks is called for each revocable license
        """
        tasks.revoke_all_licenses_task(self.subscription_plan.uuid)
        expected_calls = [mock.call(self.activated_license), mock.call(self.assigned_license)]
        mock_revoke_license.assert_has_calls(expected_calls, any_order=True)
        assert mock_execute_post_revocation_tasks.call_count == 2

    @mock.patch('license_manager.apps.subscriptions.api.execute_post_revocation_tasks')
    @mock.patch('license_manager.apps.subscriptions.api.revoke_license')
    def test_revoke_all_licenses_task_error(self, mock_revoke_license, mock_execute_post_revocation_tasks):
        """
        Verify that revoke_license handles any errors
        """
        mock_revoke_license.side_effect = [
            LicenseRevocationError(self.assigned_license.uuid, 'something terrible went wrong'),
            None
        ]

        with self.assertLogs(level='INFO') as log, pytest.raises(LicenseRevocationError):
            tasks.revoke_all_licenses_task(self.subscription_plan.uuid)

        assert mock_revoke_license.call_args_list == [mock.call(self.assigned_license)]

        assert 'Could not revoke license with uuid {} during revoke_all_licenses_task'.format(
            self.assigned_license.uuid) in log.output[0]

        assert mock_execute_post_revocation_tasks.call_count == 0


class EnterpriseEnrollmentLicenseSubsidyTaskTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()

        cls.user = UserFactory()
        cls.user2 = UserFactory()
        cls.users = [cls.user, cls.user2]
        cls.enterprise_customer_uuid = uuid4()
        cls.enterprise_catalog_uuid = uuid4()
        cls.course_key = 'testX'
        cls.lms_user_id = 1
        cls.now = localized_utcnow()
        cls.activation_key = uuid4()

        cls.customer_agreement = CustomerAgreementFactory(
            enterprise_customer_uuid=cls.enterprise_customer_uuid,
        )
        cls.active_subscription_for_customer = SubscriptionPlanFactory.create(
            customer_agreement=cls.customer_agreement,
            enterprise_catalog_uuid=cls.enterprise_catalog_uuid,
            is_active=True,
        )
        cls.activated_license = LicenseFactory.create(
            status=constants.ACTIVATED,
            user_email=cls.user.email,
            subscription_plan=cls.active_subscription_for_customer,
        )

        cls.bulk_enrollment_job = BulkEnrollmentJobFactory.create(
            enterprise_customer_uuid=cls.enterprise_customer_uuid,
            lms_user_id=cls.lms_user_id,
        )

    def tearDown(self):
        super().tearDown()
        License.objects.all().delete()
        SubscriptionPlan.objects.all().delete()
        CustomerAgreement.objects.all().delete()

    @mock.patch('license_manager.apps.api.tasks.BulkEnrollmentJob.upload_results', return_value="https://example.com/download")
    @mock.patch('license_manager.apps.api.v1.views.SubscriptionPlan.contains_content')
    @mock.patch('license_manager.apps.api_client.enterprise.EnterpriseApiClient.bulk_enroll_enterprise_learners')
    def test_bulk_enroll(self, mock_bulk_enroll_enterprise_learners, mock_contains_content, mock_upload_results):

        mock_enrollment_response = mock.Mock(spec=models.Response)
        mock_enrollment_response.json.return_value = {
            'successes': [{'email': self.user.email, 'course_run_key': self.course_key}],
            'pending': [],
            'failures': []
        }
        mock_enrollment_response.status_code = 201
        mock_bulk_enroll_enterprise_learners.return_value = mock_enrollment_response

        expected_enterprise_enrollment_request_options = {
            'licenses_info': [
                {
                    'email': self.user.email,
                    'course_run_key': self.course_key,
                    'license_uuid': str(self.activated_license.uuid)
                }
            ],
            'notify': True
        }

        results = tasks.enterprise_enrollment_license_subsidy_task(str(self.bulk_enrollment_job.uuid), self.enterprise_customer_uuid, [self.user.email], [self.course_key], True, self.active_subscription_for_customer.uuid)

        mock_bulk_enroll_enterprise_learners.assert_called_with(
            str(self.enterprise_customer_uuid),
            expected_enterprise_enrollment_request_options
        )
        mock_contains_content.assert_called_with([self.course_key])
        assert mock_contains_content.call_count == 1
        assert len(results) == 1
        assert results[0][2] == 'success'

    @mock.patch('license_manager.apps.api.tasks.BulkEnrollmentJob.upload_results', return_value="https://example.com/download")
    @mock.patch('license_manager.apps.api.v1.views.SubscriptionPlan.contains_content')
    @mock.patch('license_manager.apps.api_client.enterprise.EnterpriseApiClient.bulk_enroll_enterprise_learners')
    def test_bulk_enroll_revoked_license(self, mock_bulk_enroll_enterprise_learners, mock_contains_content, mock_upload_results):
        # random, non-existant subscription uuid
        results = tasks.enterprise_enrollment_license_subsidy_task(str(self.bulk_enrollment_job.uuid), self.enterprise_customer_uuid, [self.user2.email], [self.course_key], True, uuid4())

        mock_bulk_enroll_enterprise_learners.assert_not_called()
        assert len(results) == 1
        assert results[0][2] == 'failed'

    @mock.patch('license_manager.apps.api.tasks.BulkEnrollmentJob.upload_results', return_value="https://example.com/download")
    @mock.patch('license_manager.apps.api.v1.views.SubscriptionPlan.contains_content')
    @mock.patch('license_manager.apps.api_client.enterprise.EnterpriseApiClient.bulk_enroll_enterprise_learners')
    def test_bulk_enroll_invalid_email_addresses(self, mock_bulk_enroll_enterprise_learners, mock_contains_content, mock_upload_results):
        mock_enrollment_response = mock.Mock(spec=models.Response)
        mock_enrollment_response.json.return_value = {
            'successes': [],
            'pending': [],
            'failures': [],
            'invalid_email_addresses': [self.user.email],
        }
        mock_enrollment_response.status_code = 201
        mock_bulk_enroll_enterprise_learners.return_value = mock_enrollment_response

        results = tasks.enterprise_enrollment_license_subsidy_task(str(self.bulk_enrollment_job.uuid), self.enterprise_customer_uuid, [self.user.email], [self.course_key], True, self.active_subscription_for_customer.uuid)

        assert len(results) == 1
        assert results[0][2] == 'failed'
        assert results[0][3] == 'invalid email address'

    @mock.patch('license_manager.apps.api.tasks.BulkEnrollmentJob.upload_results', return_value="https://example.com/download")
    @mock.patch('license_manager.apps.api.v1.views.SubscriptionPlan.contains_content')
    @mock.patch('license_manager.apps.api_client.enterprise.EnterpriseApiClient.bulk_enroll_enterprise_learners')
    def test_bulk_enroll_pending(self, mock_bulk_enroll_enterprise_learners, mock_contains_content, mock_upload_results):
        mock_enrollment_response = mock.Mock(spec=models.Response)
        mock_enrollment_response.json.return_value = {
            'successes': [],
            'pending': [{'email': self.user.email, 'course_run_key': self.course_key}],
            'failures': [],
        }
        mock_enrollment_response.status_code = 202
        mock_bulk_enroll_enterprise_learners.return_value = mock_enrollment_response

        results = tasks.enterprise_enrollment_license_subsidy_task(str(self.bulk_enrollment_job.uuid), self.enterprise_customer_uuid, [self.user.email], [self.course_key], True, self.active_subscription_for_customer.uuid)

        assert len(results) == 1
        assert results[0][2] == 'pending'

    @mock.patch('license_manager.apps.api.tasks.BulkEnrollmentJob.upload_results', return_value="https://example.com/download")
    @mock.patch('license_manager.apps.api.v1.views.SubscriptionPlan.contains_content')
    @mock.patch('license_manager.apps.api_client.enterprise.EnterpriseApiClient.bulk_enroll_enterprise_learners')
    def test_bulk_enroll_failures(self, mock_bulk_enroll_enterprise_learners, mock_contains_content, mock_upload_results):
        mock_enrollment_response = mock.Mock(spec=models.Response)
        mock_enrollment_response.json.return_value = {
            'successes': [],
            'pending': [],
            'failures': [{'email': self.user.email, 'course_run_key': self.course_key}],
        }
        mock_enrollment_response.status_code = 201
        mock_bulk_enroll_enterprise_learners.return_value = mock_enrollment_response

        results = tasks.enterprise_enrollment_license_subsidy_task(str(self.bulk_enrollment_job.uuid), self.enterprise_customer_uuid, [self.user.email], [self.course_key], True, self.active_subscription_for_customer.uuid)

        assert len(results) == 1
        assert results[0][2] == 'failed'


class SendWeeklyUtilizationEmailTaskTests(TestCase):
    now = localized_utcnow()
    test_ecu_id = uuid4()
    test_email = 'test@email.com'

    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()

        customer_agreement = CustomerAgreementFactory()
        subscription_plan = SubscriptionPlanFactory(customer_agreement=customer_agreement)
        subscription_plan_details = {
            'uuid': subscription_plan.uuid,
            'title': subscription_plan.title,
            'enterprise_customer_uuid': subscription_plan.enterprise_customer_uuid,
            'enterprise_customer_name': subscription_plan.customer_agreement.enterprise_customer_name,
            'num_allocated_licenses': subscription_plan.num_allocated_licenses,
            'num_licenses': subscription_plan.num_licenses,
            'highest_utilization_threshold_reached': subscription_plan.highest_utilization_threshold_reached
        }

        cls.customer_agreement = customer_agreement
        cls.subscription_plan = subscription_plan
        cls.subscription_plan_details = subscription_plan_details

    def tearDown(self):
        """
        Deletes all licenses, and subscription after each test method is run.
        """
        super().tearDown()
        SubscriptionPlan.objects.all().delete()
        CustomerAgreement.objects.all().delete()
        Notification.objects.all().delete()

    @mock.patch('license_manager.apps.api.tasks.BrazeApiClient', return_value=mock.MagicMock())
    def test_user_activated_too_recently(self, mock_braze_api_client):
        """
        Tests that email is not sent to admins who have been active for less than a configured period of time.
        """
        tasks.send_weekly_utilization_email_task(
            self.subscription_plan_details,
            [{
                'ecu_id': self.test_ecu_id,
                'email': self.test_email,
                'created': (self.now - timedelta(days=WEEKLY_UTILIZATION_EMAIL_INTERLUDE - 1)).isoformat()
            }]
        )

        mock_braze_api_client.assert_not_called()

    @mock.patch('license_manager.apps.api.tasks.BrazeApiClient', return_value=mock.MagicMock())
    def test_user_already_received_email_for_week(self, mock_braze_api_client):
        """
        Tests that email is not sent to admins who have already recevied an email for the week.
        """
        notification = Notification(
            enterprise_customer_uuid=self.subscription_plan.enterprise_customer_uuid,
            enterprise_customer_user_uuid=self.test_ecu_id,
            subscripton_plan_id=self.subscription_plan.uuid,
            notification_type=NotificationChoices.PERIODIC_INFORMATIONAL
        )
        notification.save()

        tasks.send_weekly_utilization_email_task(
            self.subscription_plan_details,
            [{
                'ecu_id': self.test_ecu_id,
                'email': self.test_email,
                'created': (self.now - timedelta(days=8)).isoformat()
            }]
        )

        mock_braze_api_client.assert_not_called()

    @mock.patch('license_manager.apps.api.tasks.BrazeApiClient', return_value=mock.MagicMock())
    def test_send_weekly_utilization_email_task_success(self, mock_braze_api_client):
        """
        Tests that the Braze client is called and the a Notification object is created.
        """
        with freezegun.freeze_time(self.now):
            tasks.send_weekly_utilization_email_task(
                self.subscription_plan_details,
                [{
                    'ecu_id': self.test_ecu_id,
                    'email': self.test_email,
                    'created': (self.now - timedelta(days=WEEKLY_UTILIZATION_EMAIL_INTERLUDE + 1)).isoformat()
                }]
            )

            mock_send_campaign_message = mock_braze_api_client.return_value.send_campaign_message
            mock_braze_api_client.assert_called()
            mock_send_campaign_message.assert_called_with(
                settings.WEEKLY_LICENSE_UTILIZATION_CAMPAIGN,
                emails=[self.test_email],
                trigger_properties={
                    'subscription_plan_title': self.subscription_plan.title,
                    'enterprise_customer_name': self.customer_agreement.enterprise_customer_name,
                    'num_allocated_licenses': 0,
                    'num_licenses': 0
                }
            )

            notification = Notification.objects.get(
                enterprise_customer_uuid=self.subscription_plan.enterprise_customer_uuid,
                enterprise_customer_user_uuid=self.test_ecu_id,
                subscripton_plan_id=self.subscription_plan.uuid,
                notification_type=NotificationChoices.PERIODIC_INFORMATIONAL,
            )

            self.assertEqual(notification.last_sent, self.now)

    @mock.patch('license_manager.apps.api.tasks.BrazeApiClient', return_value=mock.MagicMock())
    def test_send_weekly_utilization_email_task_success_previously_sent(self, mock_braze_api_client):
        """
        Tests that the Braze client is called and the a Notification object is updated if one already exists.
        """
        notification = Notification.objects.create(
            enterprise_customer_uuid=self.subscription_plan.enterprise_customer_uuid,
            enterprise_customer_user_uuid=self.test_ecu_id,
            subscripton_plan_id=self.subscription_plan.uuid,
            notification_type=NotificationChoices.PERIODIC_INFORMATIONAL,
        )
        notification.last_sent = self.now - timedelta(days=WEEKLY_UTILIZATION_EMAIL_INTERLUDE + 1)
        notification.save()

        with freezegun.freeze_time(self.now):
            tasks.send_weekly_utilization_email_task(
                self.subscription_plan_details,
                [{
                    'ecu_id': self.test_ecu_id,
                    'email': self.test_email,
                    'created': (self.now - timedelta(days=8)).isoformat()
                }]
            )

            notification.refresh_from_db()
            mock_send_campaign_message = mock_braze_api_client.return_value.send_campaign_message
            mock_braze_api_client.assert_called()
            mock_send_campaign_message.assert_called_with(
                settings.WEEKLY_LICENSE_UTILIZATION_CAMPAIGN,
                emails=[self.test_email],
                trigger_properties={
                    'subscription_plan_title': self.subscription_plan.title,
                    'enterprise_customer_name': self.customer_agreement.enterprise_customer_name,
                    'num_allocated_licenses': 0,
                    'num_licenses': 0
                }
            )

            self.assertEqual(notification.last_sent, self.now)

    @mock.patch('license_manager.apps.api.tasks.BrazeApiClient', return_value=mock.MagicMock())
    def test_send_weekly_utilization_email_task_failure(self, mock_braze_api_client):
        """
        Tests that db commits are rolled back if an error occurs.
        """
        with freezegun.freeze_time(self.now), pytest.raises(Exception):
            mock_send_campaign_message = mock_braze_api_client.return_value.send_campaign_message
            mock_send_campaign_message.side_effect = Exception('Something went wrong')

            tasks.send_weekly_utilization_email_task(
                self.subscription_plan,
                [{
                    'ecu_id': self.test_ecu_id,
                    'email': self.test_email,
                    'created': (self.now - timedelta(days=WEEKLY_UTILIZATION_EMAIL_INTERLUDE + 1)).isoformat()
                }]
            )

            mock_braze_api_client.assert_called()
            mock_send_campaign_message.assert_called_with(
                settings.WEEKLY_LICENSE_UTILIZATION_CAMPAIGN,
                emails=[self.test_email],
                trigger_properties={
                    'subscription_plan_title': self.subscription_plan.title,
                    'enterprise_customer_name': self.customer_agreement.enterprise_customer_name,
                    'num_allocated_licenses': 0,
                    'num_licenses': 0
                }
            )

            notification = Notification.objects.filter(
                enterprise_customer_uuid=self.subscription_plan.enterprise_customer_uuid,
                enterprise_customer_user_uuid=self.test_ecu_id,
                subscripton_plan_id=self.subscription_plan.uuid,
                notification_type=NotificationChoices.PERIODIC_INFORMATIONAL,
            ).first()

            assert notification is None


@ddt.ddt
class SendUtilizationThresholdReachedEmailTaskTests(TestCase):
    now = localized_utcnow()
    test_ecu_id = uuid4()
    test_email = 'test@email.com'

    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()

        customer_agreement = CustomerAgreementFactory()
        subscription_plan = SubscriptionPlanFactory(customer_agreement=customer_agreement)
        subscription_plan_details = {
            'uuid': subscription_plan.uuid,
            'title': subscription_plan.title,
            'enterprise_customer_uuid': subscription_plan.enterprise_customer_uuid,
            'enterprise_customer_name': subscription_plan.customer_agreement.enterprise_customer_name,
            'num_allocated_licenses': subscription_plan.num_allocated_licenses,
            'num_licenses': subscription_plan.num_licenses,
            'highest_utilization_threshold_reached': subscription_plan.highest_utilization_threshold_reached
        }

        cls.customer_agreement = customer_agreement
        cls.subscription_plan = subscription_plan
        cls.subscription_plan_details = subscription_plan_details

    def tearDown(self):
        """
        Deletes all licenses, and subscription after each test method is run.
        """
        super().tearDown()
        CustomerAgreement.objects.all().delete()
        SubscriptionPlan.objects.all().delete()
        Notification.objects.all().delete()
        License.objects.all().delete()

    @mock.patch('license_manager.apps.api.tasks.BrazeApiClient', return_value=mock.MagicMock())
    def test_no_utilization_threshold_reached(self, mock_braze_api_client):
        """
        Tests that email is not sent if no utilization threshold has been reached.
        """
        tasks.send_utilization_threshold_reached_email_task(
            self.subscription_plan_details,
            [{
                'ecu_id': self.test_ecu_id,
                'email': self.test_email,
                'created': (self.now - timedelta(days=8)).isoformat()
            }]
        )

        mock_braze_api_client.assert_not_called()

    @mock.patch('license_manager.apps.api.tasks.BrazeApiClient', return_value=mock.MagicMock())
    def test_send_utilization_threshold_reached_email_task_previously_sent(self, mock_braze_api_client):
        """
        Tests that email is not sent if one has been sent before for the given threshold.
        """
        Notification.objects.create(
            enterprise_customer_uuid=self.subscription_plan.enterprise_customer_uuid,
            enterprise_customer_user_uuid=self.test_ecu_id,
            subscripton_plan_id=self.subscription_plan.uuid,
            notification_type=NotificationChoices.NO_ALLOCATIONS_REMAINING,
        )
        LicenseFactory.create(
            subscription_plan=self.subscription_plan,
            status=constants.ASSIGNED,
        )

        tasks.send_utilization_threshold_reached_email_task(
            self.subscription_plan_details,
            [{
                'ecu_id': self.test_ecu_id,
                'email': self.test_email,
                'created': (self.now - timedelta(days=8)).isoformat()
            }]
        )

        mock_braze_api_client.assert_not_called()

    @ddt.data(
        {
            'num_allocated_licenses': 1,
            'num_licenses': 1,
            'highest_utilization_threshold_reached': 1,
            'notification_type': NotificationChoices.NO_ALLOCATIONS_REMAINING,
            'campaign': 'NO_ALLOCATIONS_REMAINING_CAMPAIGN'
        },
        {
            'num_allocated_licenses': 3,
            'num_licenses': 4,
            'highest_utilization_threshold_reached': 0.75,
            'notification_type': NotificationChoices.LIMITED_ALLOCATIONS_REMAINING,
            'campaign': 'LIMITED_ALLOCATIONS_REMAINING_CAMPAIGN'
        }
    )
    @ddt.unpack
    @mock.patch('license_manager.apps.api.tasks.BrazeApiClient', return_value=mock.MagicMock())
    def test_send_utilization_threshold_reached_email_task_success(
        self,
        mock_braze_api_client,
        num_allocated_licenses,
        num_licenses,
        highest_utilization_threshold_reached,
        notification_type,
        campaign
    ):
        """
        Tests that the Braze client is called and a Notification object is created.
        """
        tasks.send_utilization_threshold_reached_email_task(
            {
                **self.subscription_plan_details,
                **{
                    'num_allocated_licenses': num_allocated_licenses,
                    'num_licenses': num_licenses,
                    'highest_utilization_threshold_reached': highest_utilization_threshold_reached
                }
            },
            [{
                'ecu_id': self.test_ecu_id,
                'email': self.test_email,
                'created': (self.now - timedelta(days=8)).isoformat()
            }]
        )

        mock_send_campaign_message = mock_braze_api_client.return_value.send_campaign_message

        mock_braze_api_client.assert_called()
        mock_send_campaign_message.assert_called_with(
            getattr(settings, campaign),
            emails=[self.test_email],
            trigger_properties={
                'subscription_plan_title': self.subscription_plan.title,
                'enterprise_customer_name': self.customer_agreement.enterprise_customer_name,
                'num_allocated_licenses': num_allocated_licenses,
                'num_licenses': num_licenses
            }
        )

        Notification.objects.get(
            enterprise_customer_uuid=self.subscription_plan.enterprise_customer_uuid,
            enterprise_customer_user_uuid=self.test_ecu_id,
            subscripton_plan_id=self.subscription_plan.uuid,
            notification_type=notification_type,
        )

    @mock.patch('license_manager.apps.api.tasks.BrazeApiClient', return_value=mock.MagicMock())
    def test_send_utilization_threshold_reached_email_task_failure(self, mock_braze_api_client):
        """
        Tests that db commits are rolled back if an error occurs.
        """
        LicenseFactory.create(subscription_plan=self.subscription_plan, status=ASSIGNED)

        with freezegun.freeze_time(self.now), pytest.raises(Exception):
            mock_send_campaign_message = mock_braze_api_client.return_value.send_campaign_message
            mock_send_campaign_message.side_effect = Exception('Something went wrong')

            tasks.send_utilization_threshold_reached_email_task(
                self.subscription_plan_details,
                [{
                    'ecu_id': self.test_ecu_id,
                    'email': self.test_email,
                    'created': (self.now - timedelta(days=8)).isoformat()
                }]
            )

            mock_braze_api_client.assert_called()
            mock_send_campaign_message.assert_called_with(
                settings.NO_ALLOCATIONS_REMAINING_CAMPAIGN,
                emails=[self.test_email],
                trigger_properties={
                    'subscription_plan_title': self.subscription_plan.title,
                    'enterprise_customer_name': self.customer_agreement.enterprise_customer_name,
                    'num_allocated_licenses': 1,
                    'num_licenses': 1
                }
            )

            notification = Notification.objects.filter(
                enterprise_customer_uuid=self.subscription_plan.enterprise_customer_uuid,
                enterprise_customer_user_uuid=self.test_ecu_id,
                subscripton_plan_id=self.subscription_plan.uuid,
                notification_type=NotificationChoices.NO_ALLOCATIONS_REMAINING,
            ).first()

            assert notification is None
