"""
Tests for the license-manager API celery tasks
"""
from datetime import datetime, timedelta
from unittest import mock
from uuid import uuid4

import ddt
import freezegun
import pytest
from braze.exceptions import BrazeClientError
from django.conf import settings
from django.test import TestCase
from django.test.utils import override_settings
from freezegun import freeze_time
from requests import models

from license_manager.apps.api import tasks
from license_manager.apps.api.tests.factories import BulkEnrollmentJobFactory
from license_manager.apps.subscriptions import constants
from license_manager.apps.subscriptions.api import revoke_license
from license_manager.apps.subscriptions.constants import (
    ASSIGNED,
    DAYS_BEFORE_INITIAL_UTILIZATION_EMAIL_SENT,
    ENTERPRISE_BRAZE_ALIAS_LABEL,
    UNASSIGNED,
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
from license_manager.apps.subscriptions.utils import (
    get_admin_portal_url,
    localized_utcnow,
)


# pylint: disable=unused-argument
@ddt.ddt
class EmailTaskTests(TestCase):
    """
    Tests for send_assignment_email_task and send_post_activation_email_task.
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
        self.contact_email = 'cool_biz@example.com'

    @mock.patch('license_manager.apps.api.tasks.BrazeApiClient', return_value=mock.MagicMock())
    def test_create_braze_aliases_task(self, mock_braze_client):
        """
        Assert create_braze_aliases_task calls Braze API with the correct arguments.
        """
        tasks.create_braze_aliases_task(
            self.email_recipient_list
        )
        mock_braze_client().create_braze_alias.assert_any_call(
            self.email_recipient_list,
            ENTERPRISE_BRAZE_ALIAS_LABEL,
        )

    @mock.patch('license_manager.apps.api.tasks.BrazeApiClient', side_effect=BrazeClientError)
    def test_create_braze_aliases_task_reraises_braze_exceptions(self, _):
        """
        Assert create_braze_aliases_task reraises any braze exceptions.
        """
        with self.assertRaises(BrazeClientError):
            tasks.create_braze_aliases_task(
                self.email_recipient_list
            )

    @mock.patch('license_manager.apps.api.tasks.EnterpriseApiClient', return_value=mock.MagicMock())
    @mock.patch('license_manager.apps.api.tasks.BrazeApiClient', return_value=mock.MagicMock())
    def test_activation_task(self, mock_braze_client, mock_enterprise_client):
        """
        Assert activation_task calls Braze API with the correct arguments.
        """
        mock_enterprise_client().get_enterprise_customer_data.return_value = {
            'slug': self.enterprise_slug,
            'name': self.enterprise_name,
            'sender_alias': self.enterprise_sender_alias,
            'contact_email': self.contact_email,
        }

        tasks.send_assignment_email_task(
            self.custom_template_text,
            self.email_recipient_list,
            self.subscription_plan.uuid,
        )

        for user_email in self.email_recipient_list:
            expected_license_key = str(self.subscription_plan.licenses.get(
                user_email=user_email
            ).activation_key)

            mock_enterprise_client().get_enterprise_customer_data.assert_any_call(
                self.subscription_plan.enterprise_customer_uuid
            )
            expected_trigger_properties = {
                'TEMPLATE_GREETING': 'Hello',
                'TEMPLATE_CLOSING': 'Goodbye',
                'license_activation_key': expected_license_key,
                'enterprise_customer_slug': self.enterprise_slug,
                'enterprise_customer_name': self.enterprise_name,
                'enterprise_sender_alias': self.enterprise_sender_alias,
                'enterprise_contact_email': self.contact_email,
            }
            expected_recipient = {
                'attributes': {'email': user_email},
                'user_alias': {
                    'alias_label': ENTERPRISE_BRAZE_ALIAS_LABEL,
                    'alias_name': user_email,
                },
            }
            mock_braze_client().send_campaign_message.assert_any_call(
                settings.BRAZE_ASSIGNMENT_EMAIL_CAMPAIGN,
                recipients=[expected_recipient],
                trigger_properties=expected_trigger_properties,
            )

    # pylint: disable=unused-argument
    @mock.patch('license_manager.apps.api.tasks.logger', return_value=mock.MagicMock())
    @mock.patch('license_manager.apps.api.tasks.BrazeApiClient', side_effect=BrazeClientError)
    @mock.patch('license_manager.apps.api.tasks.EnterpriseApiClient', return_value=mock.MagicMock())
    def test_activation_task_send_email_failure_logged(self, mock_enterprise_client, mock_braze_client, mock_logger):
        """
        Tests that when sending the activate email fails, an error gets logged
        """

        with self.assertRaises(BrazeClientError):
            mock_enterprise_client().get_enterprise_customer_data.return_value = {
                'slug': self.enterprise_slug,
                'name': self.enterprise_name,
                'sender_alias': self.enterprise_sender_alias,
                'contact_email': self.contact_email,
            }

            tasks.send_assignment_email_task(
                self.custom_template_text,
                self.email_recipient_list,
                self.subscription_plan.uuid
            )

        mock_logger.exception.assert_called_once()

    @mock.patch('license_manager.apps.api.tasks.BrazeApiClient', return_value=mock.MagicMock())
    @mock.patch('license_manager.apps.api.tasks.EnterpriseApiClient', return_value=mock.MagicMock())
    def test_send_reminder_email_task(self, mock_enterprise_client, mock_braze_client):
        """
        Assert send_reminder_email_task calls Braze API with the correct arguments
        """
        mock_enterprise_client().get_enterprise_customer_data.return_value = {
            'slug': self.enterprise_slug,
            'name': self.enterprise_name,
            'sender_alias': self.enterprise_sender_alias,
            'contact_email': self.contact_email,
        }
        with freeze_time(localized_utcnow()):
            tasks.send_reminder_email_task(
                self.custom_template_text,
                self.email_recipient_list,
                self.subscription_plan.uuid
            )

            for user_email in self.email_recipient_list:
                expected_license_key = str(self.subscription_plan.licenses.get(
                    user_email=user_email
                ).activation_key)
                mock_enterprise_client().get_enterprise_customer_data.assert_any_call(
                    self.subscription_plan.enterprise_customer_uuid
                )
                mock_braze_client().create_braze_alias.assert_any_call(
                    [user_email],
                    ENTERPRISE_BRAZE_ALIAS_LABEL,
                )

                expected_trigger_properties = {
                    'TEMPLATE_GREETING': 'Hello',
                    'TEMPLATE_CLOSING': 'Goodbye',
                    'license_activation_key': expected_license_key,
                    'enterprise_customer_slug': self.enterprise_slug,
                    'enterprise_customer_name': self.enterprise_name,
                    'enterprise_sender_alias': self.enterprise_sender_alias,
                    'enterprise_contact_email': self.contact_email,
                }
                expected_recipient = {
                    'attributes': {'email': user_email},
                    'user_alias': {
                        'alias_label': ENTERPRISE_BRAZE_ALIAS_LABEL,
                        'alias_name': user_email,
                    },
                }
                mock_braze_client().send_campaign_message.assert_any_call(
                    settings.BRAZE_ASSIGNMENT_EMAIL_CAMPAIGN,
                    recipients=[expected_recipient],
                    trigger_properties=expected_trigger_properties,
                )

            # Verify the 'last_remind_date' of all licenses have been updated
            assert_date_fields_correct(
                self.subscription_plan.licenses.filter(user_email__in=self.email_recipient_list),
                ['last_remind_date'],
                True
            )

    @mock.patch('license_manager.apps.api.tasks.BrazeApiClient', side_effect=BrazeClientError)
    @mock.patch('license_manager.apps.api.tasks.EnterpriseApiClient', return_value=mock.MagicMock())
    def test_send_reminder_email_failure_no_remind_date_update(self, mock_enterprise_client, mock_braze_client):
        """
        Tests that when sending the remind email fails, last_remind_date is not updated
        """
        mock_enterprise_client().get_enterprise_customer_data.return_value = {
            'slug': self.enterprise_slug,
            'name': self.enterprise_name,
            'sender_alias': self.enterprise_sender_alias,
            'contact_email': self.contact_email,
        }

        with self.assertRaises(BrazeClientError):
            tasks.send_reminder_email_task(
                self.custom_template_text,
                self.email_recipient_list,
                self.subscription_plan.uuid
            )

        assert_date_fields_correct(
            self.subscription_plan.licenses.filter(user_email__in=self.email_recipient_list),
            ['last_remind_date'],
            False
        )

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
            actual_subscription_plan_type,
        ) = send_email_args[:7]

        assert list(self.assigned_licenses) == list(actual_licenses)
        assert self.custom_template_text == actual_template_text
        assert self.enterprise_slug == actual_enterprise_slug
        assert self.enterprise_name == actual_enterprise_name
        assert self.enterprise_sender_alias == actual_enterprise_sender_alias
        assert self.subscription_plan_type == actual_subscription_plan_type  # pylint: disable=no-member

    @mock.patch('license_manager.apps.api.tasks.EnterpriseApiClient', return_value=mock.MagicMock())
    @mock.patch('license_manager.apps.api.tasks.BrazeApiClient', return_value=mock.MagicMock())
    def test_send_post_activation_email_task(self, mock_braze_client, mock_enterprise_client):
        """
        Tests that the onboarding email task sends the email
        """
        mock_enterprise_client().get_enterprise_customer_data.return_value = {
            'slug': self.enterprise_slug,
            'name': self.enterprise_name,
            'sender_alias': self.enterprise_sender_alias,
            'contact_email': self.contact_email,
        }

        tasks.send_post_activation_email_task(self.enterprise_uuid, self.user_email)

        mock_braze_client().create_braze_alias.assert_any_call(
            [self.user_email],
            ENTERPRISE_BRAZE_ALIAS_LABEL,
        )

        expected_trigger_properties = {
            'enterprise_customer_slug': self.enterprise_slug,
            'enterprise_customer_name': self.enterprise_name,
            'enterprise_sender_alias': self.enterprise_sender_alias,
            'enterprise_contact_email': self.contact_email,
        }
        expected_recipient = {
            'attributes': {'email': self.user_email},
            'user_alias': {
                'alias_label': ENTERPRISE_BRAZE_ALIAS_LABEL,
                'alias_name': self.user_email,
            },
        }
        mock_braze_client().send_campaign_message.assert_called_with(
            settings.BRAZE_ACTIVATION_EMAIL_CAMPAIGN,
            recipients=[expected_recipient],
            trigger_properties=expected_trigger_properties,
        )

    @mock.patch('license_manager.apps.api.tasks.EnterpriseApiClient', return_value=mock.MagicMock())
    @mock.patch('license_manager.apps.api.tasks.BrazeApiClient', side_effect=BrazeClientError)
    def test_send_post_activation_email_task_reraises_braze_exceptions(self, _, mock_enterprise_client):
        """
        Assert send_post_activation_email_task reraises any braze exceptions.
        """
        mock_enterprise_client().get_enterprise_customer_data.return_value = {
            'slug': self.enterprise_slug,
            'name': self.enterprise_name,
            'sender_alias': self.enterprise_sender_alias,
            'contact_email': self.contact_email,
        }

        with self.assertRaises(BrazeClientError):
            tasks.send_post_activation_email_task(self.enterprise_uuid, self.user_email)

    @mock.patch('license_manager.apps.api.tasks.EnterpriseApiClient', return_value=mock.MagicMock())
    @mock.patch('license_manager.apps.api.tasks.BrazeApiClient', return_value=mock.MagicMock())
    def test_revocation_cap_email_task(self, mock_braze_client, mock_enterprise_client):
        """
        Tests that the email is sent with the right arguments
        """
        mock_enterprise_client().get_enterprise_customer_data.return_value = {
            'slug': self.enterprise_slug,
            'name': self.enterprise_name,
            'sender_alias': self.enterprise_sender_alias,
            'contact_email': self.contact_email,
        }

        with freeze_time(localized_utcnow()):
            tasks.send_revocation_cap_notification_email_task(
                self.subscription_plan.uuid
            )

            mock_braze_client().create_braze_alias.assert_any_call(
                [settings.CUSTOMER_SUCCESS_EMAIL_ADDRESS],
                ENTERPRISE_BRAZE_ALIAS_LABEL,
            )

            now = localized_utcnow()
            expected_date = datetime.strftime(now, "%B %d, %Y, %I:%M%p %Z")
            expected_trigger_properties = {
                'SUBSCRIPTION_TITLE': self.subscription_plan.title,
                'NUM_REVOCATIONS_APPLIED': self.subscription_plan.num_revocations_applied,
                'ENTERPRISE_NAME': self.enterprise_name,
                'REVOKED_LIMIT_REACHED_DATE': expected_date,
            }
            expected_recipient = {
                'attributes': {'email': settings.CUSTOMER_SUCCESS_EMAIL_ADDRESS},
                'user_alias': {
                    'alias_label': ENTERPRISE_BRAZE_ALIAS_LABEL,
                    'alias_name': settings.CUSTOMER_SUCCESS_EMAIL_ADDRESS,
                },
            }
            mock_braze_client().send_campaign_message.assert_called_with(
                settings.BRAZE_REVOKE_CAP_EMAIL_CAMPAIGN,
                recipients=[expected_recipient],
                trigger_properties=expected_trigger_properties,
            )

    @mock.patch('license_manager.apps.api.tasks.EnterpriseApiClient', return_value=mock.MagicMock())
    @mock.patch('license_manager.apps.api.tasks.BrazeApiClient', side_effect=BrazeClientError)
    def test_revocation_cap_email_task_reraises_braze_exceptions(self, _, mock_enterprise_client):
        """
        Assert send_revocation_cap_notification_email_task reraises any braze exceptions.
        """
        mock_enterprise_client().get_enterprise_customer_data.return_value = {
            'slug': self.enterprise_slug,
            'name': self.enterprise_name,
            'sender_alias': self.enterprise_sender_alias,
            'contact_email': self.contact_email,
        }

        with self.assertRaises(BrazeClientError):
            tasks.send_revocation_cap_notification_email_task(
                self.subscription_plan.uuid
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
    def test_auto_applied_license_onboard_email(
        self, mock_enterprise_client, mock_braze_client, lp_search, identity_provider
    ):
        """
        Tests braze API is called when everything works as expected.
        """
        mock_enterprise_client().get_enterprise_customer_data.return_value = {
            'slug': self.enterprise_slug,
            'name': self.enterprise_name,
            'sender_alias': self.enterprise_sender_alias,
            'enable_integrated_customer_learner_portal_search': lp_search,
            'identity_provider': identity_provider,
            'contact_email': self.contact_email,
        }

        tasks.send_auto_applied_license_email_task(self.enterprise_uuid, self.user_email)

        mock_braze_client().create_braze_alias.assert_any_call(
            [self.user_email],
            ENTERPRISE_BRAZE_ALIAS_LABEL,
        )

        expected_trigger_properties = {
            'enterprise_customer_slug': self.enterprise_slug,
            'enterprise_customer_name': self.enterprise_name,
            'enterprise_contact_email': self.contact_email,
            'enterprise_sender_alias': self.enterprise_sender_alias,
        }
        expected_recipient = {
            'attributes': {'email': self.user_email},
            'user_alias': {
                'alias_label': ENTERPRISE_BRAZE_ALIAS_LABEL,
                'alias_name': self.user_email,
            },
        }

        if identity_provider and lp_search is False:
            expected_campaign_id = ''  # Empty because setting isn't set in tests
        else:
            expected_campaign_id = 'LP-campaign-id'

        mock_braze_client().send_campaign_message.assert_called_with(
            expected_campaign_id,
            recipients=[expected_recipient],
            trigger_properties=expected_trigger_properties,
        )

    @mock.patch('license_manager.apps.api.tasks.logger', return_value=mock.MagicMock())
    @mock.patch('license_manager.apps.api.tasks.BrazeApiClient', return_value=mock.MagicMock())
    @mock.patch('license_manager.apps.api.tasks.EnterpriseApiClient', side_effect=Exception)
    def test_auto_applied_license_onboard_email_ent_client_error(
        self, mock_enterprise_client, mock_braze_client, mock_logger
    ):
        """
        Tests braze API is not called if enterprise client errors.
        """
        tasks.send_auto_applied_license_email_task(self.enterprise_uuid, self.user_email)

        mock_braze_client().send_campaign_message.assert_not_called()
        mock_logger.error.assert_called_once()

    @mock.patch('license_manager.apps.api.tasks.logger', return_value=mock.MagicMock())
    @mock.patch('license_manager.apps.api.tasks.BrazeApiClient', side_effect=BrazeClientError)
    @mock.patch('license_manager.apps.api.tasks.EnterpriseApiClient', return_value=mock.MagicMock())
    def test_auto_applied_license_onboard_email_braze_client_error(
        self, mock_enterprise_client, mock_braze_client, mock_logger
    ):
        """
        Tests error logged if brazy client errors.
        """
        mock_enterprise_client().get_enterprise_customer_data.return_value = {
            'slug': self.enterprise_slug,
            'name': self.enterprise_name,
            'sender_alias': self.enterprise_sender_alias,
            'enable_integrated_customer_learner_portal_search': True,
            'identity-provider': uuid4(),
            'contact_email': self.contact_email,
        }

        tasks.send_auto_applied_license_email_task(self.enterprise_uuid, self.user_email)

        mock_logger.error.assert_called_once()


@ddt.ddt
class RevokeAllLicensesTaskTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()

        subscription_plan = SubscriptionPlanFactory()
        unassigned_license = LicenseFactory.create(status=constants.UNASSIGNED, subscription_plan=subscription_plan)
        assigned_license = LicenseFactory.create(status=constants.ASSIGNED, subscription_plan=subscription_plan)
        activated_license = LicenseFactory.create(status=constants.ACTIVATED, subscription_plan=subscription_plan)

        cls.now = localized_utcnow()
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

    @mock.patch('license_manager.apps.api.tasks.execute_post_revocation_tasks')
    @mock.patch('license_manager.apps.subscriptions.api.revoke_license')
    def test_revoke_all_licenses_task(self, mock_revoke_license, mock_execute_post_revocation_tasks):
        """
        Verify that revoke_license and execute_post_revocation_tasks is called for each revocable license
        """
        tasks.revoke_all_licenses_task(self.subscription_plan.uuid)
        expected_calls = [mock.call(self.activated_license), mock.call(self.assigned_license)]
        mock_revoke_license.assert_has_calls(expected_calls, any_order=True)
        assert mock_execute_post_revocation_tasks.call_count == 2

    @mock.patch('license_manager.apps.api.tasks.execute_post_revocation_tasks')
    @mock.patch('license_manager.apps.subscriptions.api.revoke_license')
    def test_revoke_all_licenses_task_error(self, mock_revoke_license, mock_execute_post_revocation_tasks):
        """
        Verify that revoke_license handles any errors
        """
        mock_revoke_license.side_effect = [
            LicenseRevocationError(self.assigned_license.uuid, 'something terrible went wrong'),
            None
        ]

        with pytest.raises(LicenseRevocationError):
            tasks.revoke_all_licenses_task(self.subscription_plan.uuid)

        assert len(mock_revoke_license.call_args_list) == 1
        revokable_licenses = [self.activated_license.uuid, self.assigned_license.uuid]
        assert mock_revoke_license.call_args_list[0][0][0].uuid in revokable_licenses
        assert mock_execute_post_revocation_tasks.call_count == 0

    @ddt.data(
        {'original_status': constants.ACTIVATED, 'revoke_max_percentage': 200},
        {'original_status': constants.ACTIVATED, 'revoke_max_percentage': 100},
        {'original_status': constants.ASSIGNED, 'revoke_max_percentage': 100}
    )
    @ddt.unpack
    @mock.patch('license_manager.apps.api.tasks.revoke_course_enrollments_for_user_task.delay')
    @mock.patch('license_manager.apps.api.tasks.send_revocation_cap_notification_email_task.delay')
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

        with freezegun.freeze_time(self.now):
            revocation_result = revoke_license(original_license)
            tasks.execute_post_revocation_tasks(**revocation_result)

        is_license_revoked = original_status == constants.ACTIVATED
        revoke_limit_reached = is_license_revoked and revoke_max_percentage <= 100

        self.assertEqual(mock_revoke_enrollments_delay.called, is_license_revoked)
        self.assertEqual(mock_cap_email_delay.called, revoke_limit_reached)


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

    @mock.patch(
        'license_manager.apps.api.tasks.BulkEnrollmentJob.upload_results', return_value="https://example.com/download"
    )
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

        results = tasks.enterprise_enrollment_license_subsidy_task(
            str(self.bulk_enrollment_job.uuid),
            self.enterprise_customer_uuid,
            [self.user.email],
            [self.course_key],
            True,
            self.active_subscription_for_customer.uuid
        )

        mock_bulk_enroll_enterprise_learners.assert_called_with(
            str(self.enterprise_customer_uuid),
            expected_enterprise_enrollment_request_options
        )
        mock_contains_content.assert_called_with([self.course_key])
        assert mock_contains_content.call_count == 1
        assert len(results) == 1
        assert results[0][2] == 'success'

    @mock.patch(
        'license_manager.apps.api.tasks.BulkEnrollmentJob.upload_results', return_value="https://example.com/download"
    )
    @mock.patch('license_manager.apps.api.v1.views.SubscriptionPlan.contains_content')
    @mock.patch('license_manager.apps.api_client.enterprise.EnterpriseApiClient.bulk_enroll_enterprise_learners')
    def test_bulk_enroll_revoked_license(
        self, mock_bulk_enroll_enterprise_learners, mock_contains_content, mock_upload_results
    ):
        # random, non-existant subscription uuid
        results = tasks.enterprise_enrollment_license_subsidy_task(
            str(self.bulk_enrollment_job.uuid),
            self.enterprise_customer_uuid,
            [self.user2.email],
            [self.course_key],
            True,
            uuid4(),
        )

        mock_bulk_enroll_enterprise_learners.assert_not_called()
        assert len(results) == 1
        assert results[0][2] == 'failed'

    @mock.patch(
        'license_manager.apps.api.tasks.BulkEnrollmentJob.upload_results', return_value="https://example.com/download"
    )
    @mock.patch('license_manager.apps.api.v1.views.SubscriptionPlan.contains_content')
    @mock.patch('license_manager.apps.api_client.enterprise.EnterpriseApiClient.bulk_enroll_enterprise_learners')
    def test_bulk_enroll_invalid_email_addresses(
        self, mock_bulk_enroll_enterprise_learners, mock_contains_content, mock_upload_results
    ):
        mock_enrollment_response = mock.Mock(spec=models.Response)
        mock_enrollment_response.json.return_value = {
            'successes': [],
            'pending': [],
            'failures': [],
            'invalid_email_addresses': [self.user.email],
        }
        mock_enrollment_response.status_code = 201
        mock_bulk_enroll_enterprise_learners.return_value = mock_enrollment_response

        results = tasks.enterprise_enrollment_license_subsidy_task(
            str(self.bulk_enrollment_job.uuid),
            self.enterprise_customer_uuid,
            [self.user.email],
            [self.course_key],
            True,
            self.active_subscription_for_customer.uuid,
        )

        assert len(results) == 1
        assert results[0][2] == 'failed'
        assert results[0][3] == 'invalid email address'

    @mock.patch(
        'license_manager.apps.api.tasks.BulkEnrollmentJob.upload_results', return_value="https://example.com/download"
    )
    @mock.patch('license_manager.apps.api.v1.views.SubscriptionPlan.contains_content')
    @mock.patch('license_manager.apps.api_client.enterprise.EnterpriseApiClient.bulk_enroll_enterprise_learners')
    def test_bulk_enroll_pending(
        self, mock_bulk_enroll_enterprise_learners, mock_contains_content, mock_upload_results
    ):
        mock_enrollment_response = mock.Mock(spec=models.Response)
        mock_enrollment_response.json.return_value = {
            'successes': [],
            'pending': [{'email': self.user.email, 'course_run_key': self.course_key}],
            'failures': [],
        }
        mock_enrollment_response.status_code = 202
        mock_bulk_enroll_enterprise_learners.return_value = mock_enrollment_response

        results = tasks.enterprise_enrollment_license_subsidy_task(
            str(self.bulk_enrollment_job.uuid), self.enterprise_customer_uuid,
            [self.user.email], [self.course_key],
            True, self.active_subscription_for_customer.uuid,
        )

        assert len(results) == 1
        assert results[0][2] == 'pending'

    @mock.patch(
        'license_manager.apps.api.tasks.BulkEnrollmentJob.upload_results', return_value="https://example.com/download"
    )
    @mock.patch('license_manager.apps.api.v1.views.SubscriptionPlan.contains_content')
    @mock.patch('license_manager.apps.api_client.enterprise.EnterpriseApiClient.bulk_enroll_enterprise_learners')
    def test_bulk_enroll_failures(
        self, mock_bulk_enroll_enterprise_learners, mock_contains_content, mock_upload_results
    ):
        mock_enrollment_response = mock.Mock(spec=models.Response)
        mock_enrollment_response.json.return_value = {
            'successes': [],
            'pending': [],
            'failures': [{'email': self.user.email, 'course_run_key': self.course_key}],
        }
        mock_enrollment_response.status_code = 201
        mock_bulk_enroll_enterprise_learners.return_value = mock_enrollment_response

        results = tasks.enterprise_enrollment_license_subsidy_task(
            str(self.bulk_enrollment_job.uuid), self.enterprise_customer_uuid,
            [self.user.email], [self.course_key],
            True, self.active_subscription_for_customer.uuid,
        )

        assert len(results) == 1
        assert results[0][2] == 'failed'


class BaseLicenseUtilizationEmailTaskTests(TestCase):
    now = localized_utcnow()
    test_ecu_id = uuid4()
    test_lms_user_id = uuid4()
    test_email = 'test@email.com'
    test_admin_user = {
        'id': test_lms_user_id,
        'ecu_id': test_ecu_id,
        'email': test_email
    }

    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()

        customer_agreement = CustomerAgreementFactory()
        subscription_plan = SubscriptionPlanFactory(
            customer_agreement=customer_agreement, should_auto_apply_licenses=True,
        )
        expected_recipients = [
            {
                'external_user_id': cls.test_lms_user_id,
                'trigger_properties': {
                    'email': cls.test_email
                }
            }
        ]
        expected_trigger_properties = {
            'subscription_plan_title': subscription_plan.title,
            'subscription_plan_expiration_date': datetime.strftime(subscription_plan.expiration_date, "%b %-d, %Y"),
            'enterprise_customer_name': subscription_plan.customer_agreement.enterprise_customer_name,
            'num_allocated_licenses': subscription_plan.num_allocated_licenses,
            'num_licenses': subscription_plan.num_licenses,
            'admin_portal_url': get_admin_portal_url(subscription_plan.customer_agreement.enterprise_customer_slug),
            'num_auto_applied_licenses_since_turned_on': subscription_plan.auto_applied_licenses_count_since()
        }

        cls.customer_agreement = customer_agreement
        cls.subscription_plan = subscription_plan
        cls.expected_recipients = expected_recipients
        cls.expected_trigger_properties = expected_trigger_properties

    def tearDown(self):
        """
        Deletes all licenses, and subscription after each test method is run.
        """
        super().tearDown()
        CustomerAgreement.objects.all().delete()
        SubscriptionPlan.objects.all().delete()
        Notification.objects.all().delete()
        License.objects.all().delete()


class SendInitialUtilizationEmailTaskTests(BaseLicenseUtilizationEmailTaskTests):
    def _make_plan_eligible_for_email(self):
        """
        Update plan history so that it's eligible for the initial utilization email.
        """
        latest_history = self.subscription_plan.history.latest()
        latest_history.history_date = self.now - timedelta(days=DAYS_BEFORE_INITIAL_UTILIZATION_EMAIL_SENT)
        latest_history.save()

    @mock.patch('license_manager.apps.api.tasks.EnterpriseApiClient', return_value=mock.MagicMock())
    @mock.patch('license_manager.apps.api.tasks.BrazeApiClient', return_value=mock.MagicMock())
    def test_email_already_sent(self, mock_braze_api_client, mock_enterprise_api_client):
        """
        Tests that email is not sent if it's already been sent before.
        """
        notification = Notification(
            enterprise_customer_uuid=self.subscription_plan.enterprise_customer_uuid,
            enterprise_customer_user_uuid=self.test_ecu_id,
            subscripton_plan_id=self.subscription_plan.uuid,
            notification_type=NotificationChoices.PERIODIC_INFORMATIONAL
        )
        notification.save()

        tasks.send_initial_utilization_email_task(self.subscription_plan.uuid)

        mock_enterprise_api_client.assert_not_called()
        mock_braze_api_client.assert_not_called()

    @mock.patch('license_manager.apps.api.tasks.EnterpriseApiClient', return_value=mock.MagicMock())
    @mock.patch('license_manager.apps.api.tasks.BrazeApiClient', return_value=mock.MagicMock())
    def test_send_initial_utilization_email_task(self, mock_braze_api_client, mock_enterprise_api_client):
        """
        Tests that the Braze client is called and a Notification object is created.
        """
        self._make_plan_eligible_for_email()

        mock_enterprise_api_client().get_enterprise_admin_users.return_value = [self.test_admin_user]
        mock_send_campaign_message = mock_braze_api_client.return_value.send_campaign_message

        with freezegun.freeze_time(self.now):
            tasks.send_initial_utilization_email_task(self.subscription_plan.uuid)
            mock_braze_api_client.assert_called()
            mock_send_campaign_message.assert_called_with(
                settings.INITIAL_LICENSE_UTILIZATION_CAMPAIGN,
                recipients=self.expected_recipients,
                trigger_properties=self.expected_trigger_properties
            )

            notification = Notification.objects.get(
                enterprise_customer_uuid=self.subscription_plan.enterprise_customer_uuid,
                enterprise_customer_user_uuid=self.test_ecu_id,
                subscripton_plan_id=self.subscription_plan.uuid,
                notification_type=NotificationChoices.PERIODIC_INFORMATIONAL,
            )

            self.assertEqual(notification.last_sent, self.now)

    @mock.patch('license_manager.apps.api.tasks.EnterpriseApiClient', return_value=mock.MagicMock())
    @mock.patch('license_manager.apps.api.tasks.BrazeApiClient', return_value=mock.MagicMock())
    def test_send_initial_utilization_email_task_failure(self, mock_braze_api_client, mock_enterprise_api_client):
        """
        Tests that db commits are rolled back if an error occurs.
        """
        self._make_plan_eligible_for_email()

        mock_enterprise_api_client().get_enterprise_admin_users.return_value = [self.test_admin_user]
        mock_send_campaign_message = mock_braze_api_client.return_value.send_campaign_message

        with freezegun.freeze_time(self.now), pytest.raises(Exception):
            mock_send_campaign_message = mock_braze_api_client.return_value.send_campaign_message
            mock_send_campaign_message.side_effect = Exception('Something went wrong')

            tasks.send_initial_utilization_email_task(self.subscription_plan)

            mock_braze_api_client.assert_called()
            mock_send_campaign_message.assert_called_with(
                settings.INITIAL_LICENSE_UTILIZATION_CAMPAIGN,
                recipients=self.expected_recipients,
                trigger_properties=self.expected_trigger_properties
            )

            notification = Notification.objects.filter(
                enterprise_customer_uuid=self.subscription_plan.enterprise_customer_uuid,
                enterprise_customer_user_uuid=self.test_ecu_id,
                subscripton_plan_id=self.subscription_plan.uuid,
                notification_type=NotificationChoices.PERIODIC_INFORMATIONAL,
            ).first()

            assert notification is None


@ddt.ddt
class SendUtilizationThresholdReachedEmailTaskTests(BaseLicenseUtilizationEmailTaskTests):
    def _create_licenses(self, num_allocated_licenses, num_licenses):
        """
        Create licenses to reach a utilization threshold.
        """
        LicenseFactory.create_batch(
            num_allocated_licenses,
            subscription_plan=self.subscription_plan,
            status=ASSIGNED
        )
        LicenseFactory.create_batch(
            num_licenses - num_allocated_licenses,
            subscription_plan=self.subscription_plan,
            status=UNASSIGNED
        )

    @mock.patch('license_manager.apps.api.tasks.EnterpriseApiClient', return_value=mock.MagicMock())
    @mock.patch('license_manager.apps.api.tasks.BrazeApiClient', return_value=mock.MagicMock())
    def test_no_utilization_threshold_reached(self, mock_braze_api_client, mock_enterprise_api_client):
        """
        Tests that email is not sent if no utilization threshold has been reached.
        """
        tasks.send_utilization_threshold_reached_email_task(self.subscription_plan.uuid)

        mock_enterprise_api_client.assert_not_called()
        mock_braze_api_client.assert_not_called()

    @mock.patch('license_manager.apps.api.tasks.EnterpriseApiClient', return_value=mock.MagicMock())
    @mock.patch('license_manager.apps.api.tasks.BrazeApiClient', return_value=mock.MagicMock())
    def test_send_utilization_threshold_reached_email_task_previously_sent(
        self, mock_braze_api_client, mock_enterprise_api_client
    ):
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

        tasks.send_utilization_threshold_reached_email_task(self.subscription_plan.uuid)

        mock_enterprise_api_client.assert_not_called()
        mock_braze_api_client.assert_not_called()

    @ddt.data(
        {
            'num_allocated_licenses': 1,
            'num_licenses': 1,
            'notification_type': NotificationChoices.NO_ALLOCATIONS_REMAINING,
            'campaign': 'NO_ALLOCATIONS_REMAINING_CAMPAIGN'
        },
        {
            'num_allocated_licenses': 3,
            'num_licenses': 4,
            'notification_type': NotificationChoices.LIMITED_ALLOCATIONS_REMAINING,
            'campaign': 'LIMITED_ALLOCATIONS_REMAINING_CAMPAIGN'
        }
    )
    @ddt.unpack
    @mock.patch('license_manager.apps.api.tasks.EnterpriseApiClient', return_value=mock.MagicMock())
    @mock.patch('license_manager.apps.api.tasks.BrazeApiClient', return_value=mock.MagicMock())
    def test_send_utilization_threshold_reached_email_task_success(
        self,
        mock_braze_api_client,
        mock_enterprise_api_client,
        num_allocated_licenses,
        num_licenses,
        notification_type,
        campaign
    ):
        """
        Tests that the Braze client is called and a Notification object is created.
        """

        self._create_licenses(num_allocated_licenses, num_licenses)
        mock_enterprise_api_client().get_enterprise_admin_users.return_value = [self.test_admin_user]
        tasks.send_utilization_threshold_reached_email_task(self.subscription_plan.uuid)

        mock_send_campaign_message = mock_braze_api_client.return_value.send_campaign_message
        mock_braze_api_client.assert_called()
        mock_send_campaign_message.assert_called_with(
            getattr(settings, campaign),
            recipients=self.expected_recipients,
            trigger_properties={
                **self.expected_trigger_properties,
                **{
                    'num_allocated_licenses': num_allocated_licenses,
                    'num_licenses': num_licenses,
                }
            }
        )

        Notification.objects.get(
            enterprise_customer_uuid=self.subscription_plan.enterprise_customer_uuid,
            enterprise_customer_user_uuid=self.test_ecu_id,
            subscripton_plan_id=self.subscription_plan.uuid,
            notification_type=notification_type,
        )

    @mock.patch('license_manager.apps.api.tasks.EnterpriseApiClient', return_value=mock.MagicMock())
    @mock.patch('license_manager.apps.api.tasks.BrazeApiClient', return_value=mock.MagicMock())
    def test_send_utilization_threshold_reached_email_task_failure(
        self, mock_braze_api_client, mock_enterprise_api_client
    ):
        """
        Tests that db commits are rolled back if an error occurs.
        """
        self._create_licenses(1, 1)

        with pytest.raises(Exception):
            mock_send_campaign_message = mock_braze_api_client.return_value.send_campaign_message
            mock_send_campaign_message.side_effect = Exception('Something went wrong')
            mock_enterprise_api_client().get_enterprise_admin_users.return_value = [self.test_admin_user]

            tasks.send_utilization_threshold_reached_email_task(self.subscription_plan.uuid)

            mock_braze_api_client.assert_called()
            mock_send_campaign_message.assert_called_with(
                settings.NO_ALLOCATIONS_REMAINING_CAMPAIGN,
                recipients=self.expected_recipients,
                trigger_properties=self.expected_trigger_properties
            )

            notification = Notification.objects.filter(
                enterprise_customer_uuid=self.subscription_plan.enterprise_customer_uuid,
                enterprise_customer_user_uuid=self.test_ecu_id,
                subscripton_plan_id=self.subscription_plan.uuid,
                notification_type=NotificationChoices.NO_ALLOCATIONS_REMAINING,
            ).first()

            assert notification is None


class TrackLicenseChangesTests(TestCase):
    """
    Tests for track_license_changes_task.
    """
    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        cls.subscription_plan = SubscriptionPlanFactory()

    @mock.patch('license_manager.apps.subscriptions.event_utils.track_event')
    def test_licenses_created(self, mock_track_event):
        """
        Tests that an underlying ``track_event()`` call is made when licenses are created.
        """
        unassigned_licenses = LicenseFactory.create_batch(
            10,
            status=constants.UNASSIGNED,
            subscription_plan=self.subscription_plan,
        )
        provided_properties = {'superfluous_key': 'superfluous value'}
        license_uuid_strs = [str(_lic.uuid) for _lic in unassigned_licenses]

        # pylint: disable=no-value-for-parameter
        tasks.track_license_changes_task(
            license_uuid_strs,
            constants.SegmentEvents.LICENSE_CREATED,
            properties=provided_properties,
        )

        assert mock_track_event.call_count == 10
        license_uuid_superset = set(license_uuid_strs)
        for call in mock_track_event.call_args_list:
            assert call[0][0] is None
            assert call[0][1] == constants.SegmentEvents.LICENSE_CREATED
            actual_properties = call[0][2]
            assert 'superfluous_key' in actual_properties
            assert actual_properties['license_uuid'] in license_uuid_superset

    @mock.patch('license_manager.apps.subscriptions.event_utils.track_event')
    def test_licenses_assigned(self, mock_track_event):
        """
        Tests that an underlying ``track_event()`` call is made when licenses are created.
        """
        alice_license = LicenseFactory.create(
            lms_user_id=1,
            user_email='alice@example.com',
            status=constants.ASSIGNED,
            subscription_plan=self.subscription_plan,
        )
        bob_license = LicenseFactory.create(
            lms_user_id=2,
            user_email='bob@example.com',
            status=constants.ASSIGNED,
            subscription_plan=self.subscription_plan,
        )
        license_uuid_strs = [
            str(alice_license.uuid),
            str(bob_license.uuid),
        ]

        # pylint: disable=no-value-for-parameter
        tasks.track_license_changes_task(
            license_uuid_strs,
            constants.SegmentEvents.LICENSE_ASSIGNED,
        )

        assert mock_track_event.call_count == 2
        actual_properties = []
        actual_lms_user_ids = []
        for call in mock_track_event.call_args_list:
            user_id_arg, event_name_arg, properties_arg = call[0]
            assert event_name_arg == constants.SegmentEvents.LICENSE_ASSIGNED
            actual_lms_user_ids.append(user_id_arg)
            actual_properties.append(properties_arg)

        for _license in (alice_license, bob_license):
            assert str(_license.uuid) in [props['license_uuid'] for props in actual_properties]
            assert _license.user_email in [props['assigned_email'] for props in actual_properties]
            assert _license.lms_user_id in [props['assigned_lms_user_id'] for props in actual_properties]
