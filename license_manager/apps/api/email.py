import logging
from datetime import datetime

from django.conf import settings

from license_manager.apps.api_client.braze import BrazeApiClient
from license_manager.apps.api_client.mailchimp import (
    MailchimpTransactionalApiClient,
)
from license_manager.apps.subscriptions.constants import (
    REMIND_EMAIL_ACTION_TYPE,
)
from license_manager.apps.subscriptions.event_utils import (
    get_license_tracking_properties,
)
from license_manager.apps.subscriptions.utils import (
    get_admin_portal_url,
    get_enterprise_sender_alias,
)


logger = logging.getLogger(__name__)
LICENSE_DEBUG_PREFIX = '[LICENSE DEBUGGING]'


class EmailClient:
    """Wrapper class to create context and send emails based on underlying client"""
    def __init__(self) -> None:
        if settings.TRANSACTIONAL_MAIL_SERVICE == 'braze':
            self._braze_client = BrazeApiClient(logger_prefix=LICENSE_DEBUG_PREFIX)
        elif settings.TRANSACTIONAL_MAIL_SERVICE == 'mailchimp':
            self._mailchimp_client = MailchimpTransactionalApiClient(logger_prefix=LICENSE_DEBUG_PREFIX)
        else:
            raise ValueError("Please set TRANSACTIONAL_MAIL_SERVICE setting to either 'braze' or 'mailchimp'.")

    def send_assignment_or_reminder_email(
        self,
        pending_licenses,
        enterprise_customer,
        custom_template_text,
        action_type
    ):
        """Helper function to send a assignment notification or reminder email.

        Args:
            pending_licenses (list[License]): List of pending license objects
            enterprise_customer (dict): enterprise customer information
            custom_template_text (dict): Dictionary containing `greeting` and `closing` keys to be used for customizing
                the email template.
            action_type (str): A string used in logging messages to indicate which type of notification
                is being sent and determine template for email.
        Returns:
            dict of pending license by email
        """
        enterprise_slug = enterprise_customer.get('slug')
        enterprise_name = enterprise_customer.get('name')
        enterprise_sender_alias = get_enterprise_sender_alias(enterprise_customer)
        enterprise_contact_email = enterprise_customer.get('contact_email')
        pending_license_by_email = {}
        user_emails = []
        messages = []
        recipient_metadata = []
        for pending_license in pending_licenses:
            user_email = pending_license.user_email
            pending_license_by_email[user_email] = pending_license
            license_activation_key = str(pending_license.activation_key)
            if settings.TRANSACTIONAL_MAIL_SERVICE == 'braze':
                user_emails.append(user_email)
                trigger_properties = {
                    'TEMPLATE_GREETING': custom_template_text['greeting'],
                    'TEMPLATE_CLOSING': custom_template_text['closing'],
                    'license_activation_key': license_activation_key,
                    'enterprise_customer_slug': enterprise_slug,
                    'enterprise_customer_name': enterprise_name,
                    'enterprise_sender_alias': enterprise_sender_alias,
                    'enterprise_contact_email': enterprise_contact_email,
                }
                recipient = self._braze_client.aliased_recipient_object_from_email(user_email)
                recipient['attributes'].update(get_license_tracking_properties(pending_license))
                recipient['trigger_properties'] = trigger_properties
                messages.append(recipient)
            elif settings.TRANSACTIONAL_MAIL_SERVICE == 'mailchimp':
                user_emails.append({'email': user_email})
                template_context = [
                    {'name': 'TEMPLATE_GREETING', 'content': custom_template_text['greeting']},
                    {'name': 'TEMPLATE_CLOSING', 'content': custom_template_text['closing']},
                    {'name': 'license_activation_key', 'content': license_activation_key},
                    {'name': 'enterprise_customer_slug', 'content': enterprise_slug},
                    {'name': 'enterprise_customer_name', 'content': enterprise_name},
                    {'name': 'enterprise_sender_alias', 'content': enterprise_sender_alias},
                    {'name': 'enterprise_contact_email', 'content': enterprise_contact_email},
                ]
                messages.append({'rcpt': user_email, 'vars': template_context})
                recipient_metadata.append(
                    {
                        'rcpt': user_email,
                        'values': {'email': user_email}.update(get_license_tracking_properties(pending_license)),
                    }
                )
        if settings.TRANSACTIONAL_MAIL_SERVICE == 'braze':
            campaign_id = settings.BRAZE_REMIND_EMAIL_CAMPAIGN if action_type == REMIND_EMAIL_ACTION_TYPE \
                else settings.BRAZE_ASSIGNMENT_EMAIL_CAMPAIGN
            self._braze_client.send_emails(
                campaign_id,
                recipients=messages,
                user_emails=user_emails,
                success_msg=(
                    f'{LICENSE_DEBUG_PREFIX} Sent license {action_type} emails '
                    f'braze campaign {campaign_id} to {user_emails}'
                ),
                err_msg=(f'Error hitting Braze API {action_type} email to {campaign_id} for license failed.'),
            )
        elif settings.TRANSACTIONAL_MAIL_SERVICE == 'mailchimp':
            if action_type == REMIND_EMAIL_ACTION_TYPE:
                template_name = settings.MAILCHIMP_REMINDER_EMAIL_TEMPLATE
                subject = settings.MAILCHIMP_REMINDER_EMAIL_SUBJECT
            else:
                template_name = settings.MAILCHIMP_ASSIGNMENT_EMAIL_TEMPLATE
                subject = settings.MAILCHIMP_ASSIGNMENT_EMAIL_SUBJECT

            self._mailchimp_client.send_emails(
                template_name,
                merge_vars=messages,
                to_users=user_emails,
                subject=subject,
                recipient_metadata=recipient_metadata,
                success_msg=(
                    f'{LICENSE_DEBUG_PREFIX} Sent license {action_type} emails '
                    f'mailchimp template {template_name} to {user_emails}'
                ),
                err_msg=(f'Error hitting Mailchimp API {action_type} email to {template_name} for license failed.'),
            )
        return pending_license_by_email

    def send_post_activation_email(self, enterprise_customer, user_email):
        """Helper function to send post activation email

        Args:
            enterprise_customer (dict): enterprise customer information
            user_email (str): user email id
        """
        enterprise_name = enterprise_customer.get('name')
        enterprise_slug = enterprise_customer.get('slug')
        enterprise_sender_alias = get_enterprise_sender_alias(enterprise_customer)
        enterprise_contact_email = enterprise_customer.get('contact_email')
        if settings.TRANSACTIONAL_MAIL_SERVICE == 'braze':
            template_context = {
                'enterprise_customer_slug': enterprise_slug,
                'enterprise_customer_name': enterprise_name,
                'enterprise_sender_alias': enterprise_sender_alias,
                'enterprise_contact_email': enterprise_contact_email,
            }
            self._braze_client.send_single_email(
                template_context,
                user_email,
                settings.BRAZE_ACTIVATION_EMAIL_CAMPAIGN,
                err_message=f'Error hitting Braze API. Onboarding email to {user_email} for license failed.',
                create_alias=True,
            )
        elif settings.TRANSACTIONAL_MAIL_SERVICE == 'mailchimp':
            merge_vars = [
                {'name': 'enterprise_customer_slug', 'content': enterprise_slug},
                {'name': 'enterprise_customer_name', 'content': enterprise_name},
                {'name': 'enterprise_sender_alias', 'content': enterprise_sender_alias},
                {'name': 'enterprise_contact_email', 'content': enterprise_contact_email},
            ]
            self._mailchimp_client.send_single_email(
                merge_vars,
                user_email,
                subject=settings.MAILCHIMP_ACTIVATION_EMAIL_SUBJECT,
                template_slug=settings.MAILCHIMP_ACTIVATION_EMAIL_TEMPLATE,
                err_message=f'Error hitting Mailchimp API. Onboarding email to {user_email} for license failed.',
            )

    def send_auto_applied_license_email(self, enterprise_customer, user_email):
        """Helper function to send auto applied license email

        Args:
            enterprise_customer (dict): enterprise customer information
            user_email (str): user email id
        """
        enterprise_slug = enterprise_customer.get('slug')
        enterprise_name = enterprise_customer.get('name')
        learner_portal_search_enabled = enterprise_customer.get('enable_integrated_customer_learner_portal_search')
        identity_provider = enterprise_customer.get('identity_provider')
        enterprise_sender_alias = get_enterprise_sender_alias(enterprise_customer)
        enterprise_contact_email = enterprise_customer.get('contact_email')

        if settings.TRANSACTIONAL_MAIL_SERVICE == 'braze':
            if identity_provider and learner_portal_search_enabled is False:
                braze_campaign_id = settings.AUTOAPPLY_NO_LEARNER_PORTAL_CAMPAIGN
            else:
                braze_campaign_id = settings.AUTOAPPLY_WITH_LEARNER_PORTAL_CAMPAIGN

            # Form data we want to hand to the campaign's email template
            braze_trigger_properties = {
                'enterprise_customer_slug': enterprise_slug,
                'enterprise_customer_name': enterprise_name,
                'enterprise_sender_alias': enterprise_sender_alias,
                'enterprise_contact_email': enterprise_contact_email,
            }
            self._braze_client.send_single_email(
                braze_trigger_properties,
                user_email,
                braze_campaign_id,
                err_message=(
                    f'Error hitting Braze API. Onboarding email to {user_email} for auto applied license failed.'
                ),
                create_alias=True,
            )
        elif settings.TRANSACTIONAL_MAIL_SERVICE == 'mailchimp':
            if identity_provider and learner_portal_search_enabled is False:
                template_slug = settings.MAILCHIMP_AUTOAPPLY_NO_LEARNER_PORTAL_TEMPLATE
                subject = settings.MAILCHIMP_AUTOAPPLY_NO_LEARNER_PORTAL_SUBJECT
            else:
                template_slug = settings.MAILCHIMP_AUTOAPPLY_WITH_LEARNER_PORTAL_TEMPLATE
                subject = settings.MAILCHIMP_AUTOAPPLY_WITH_LEARNER_PORTAL_SUBJECT
            merge_vars = [
                {'name': 'enterprise_customer_slug', 'content': enterprise_slug},
                {'name': 'enterprise_customer_name', 'content': enterprise_name},
                {'name': 'enterprise_sender_alias', 'content': enterprise_sender_alias},
                {'name': 'enterprise_contact_email', 'content': enterprise_contact_email},
            ]
            self._mailchimp_client.send_single_email(
                merge_vars,
                user_email,
                subject=subject,
                template_slug=template_slug,
                err_message=(
                    f'Error hitting Mailchimp API. Onboarding email to {user_email} for auto applied license failed.'
                ),
            )

    def send_revocation_cap_notification_email(self, subscription_plan, enterprise_name, revocation_date):
        """Helper function to send revocation notification email.

        Args:
            subscription_plan (SubscriptionPlan): SubscriptionPlan object
            enterprise_name (str): enterprise customer name
            revocation_date (str): date in `%B %d, %Y, %I:%M%p %Z` format
        """
        if settings.TRANSACTIONAL_MAIL_SERVICE == 'braze':
            braze_campaign_id = settings.BRAZE_REVOKE_CAP_EMAIL_CAMPAIGN
            braze_trigger_properties = {
                'SUBSCRIPTION_TITLE': subscription_plan.title,
                'NUM_REVOCATIONS_APPLIED': subscription_plan.num_revocations_applied,
                'ENTERPRISE_NAME': enterprise_name,
                'REVOKED_LIMIT_REACHED_DATE': revocation_date,
            }
            self._braze_client.send_single_email(
                braze_trigger_properties,
                settings.CUSTOMER_SUCCESS_EMAIL_ADDRESS,
                braze_campaign_id,
                err_message='Revocation cap notification email sending received an exception.',
                create_alias=True,
            )
        elif settings.TRANSACTIONAL_MAIL_SERVICE == 'mailchimp':
            template_slug = settings.MAILCHIMP_REVOKE_CAP_EMAIL_TEMPLATE
            merge_vars = [
                {'name': 'SUBSCRIPTION_TITLE', 'content': subscription_plan.title},
                {'name': 'NUM_REVOCATIONS_APPLIED', 'content': subscription_plan.num_revocations_applied},
                {'name': 'ENTERPRISE_NAME', 'content': enterprise_name},
                {'name': 'REVOKED_LIMIT_REACHED_DATE', 'content': revocation_date},
            ]
            self._mailchimp_client.send_single_email(
                merge_vars,
                settings.CUSTOMER_SUCCESS_EMAIL_ADDRESS,
                subject=settings.MAILCHIMP_REVOKE_CAP_EMAIL_SUBJECT,
                template_slug=template_slug,
                err_message='Revocation cap notification email sending received an exception.',
            )

    def send_bulk_enrollment_results_email(self, enterprise_customer, bulk_enrollment_job, admin_users):
        """Helper function to send bulk enrollment results to admins.

        Args:
            enterprise_customer (dict): enterprise customer information
            bulk_enrollment_job (BulkEnrollmentJob): the completed bulk enrollment job
            admin_users (list[{
                'id': str,
                'username': str,
                'first_name': str,
                'last_name': str,
                'email': str,
                'is_staff': bool,
                'is_active': bool,
                'date_joined': str,
                'ecu_id': str,
                'created': str
            }]): list of dictionaries containing admin user information
        """
        if settings.TRANSACTIONAL_MAIL_SERVICE == 'braze':
            campaign_id = settings.BULK_ENROLL_RESULT_CAMPAIGN
            # https://web.archive.org/web/20211122135949/https://www.braze.com/docs/api/objects_filters/recipient_object/
            recipients = []
            for user in admin_users:
                if int(user['id']) != bulk_enrollment_job.lms_user_id:
                    continue
                # must use a mix of send_to_existing_only: false + enternal_id
                # w/ attributes to send to new braze profiles
                recipient = {
                    'send_to_existing_only': False,
                    'external_user_id': str(user['id']),
                    'attributes': {
                        'email': user['email'],
                    },
                }
                recipients.append(recipient)
                break
            self._braze_client.send_emails(
                campaign_id,
                recipients,
                success_msg=(
                    f'success _send_bulk_enrollment_results_email for '
                    f'bulk_enrollment_job_uuid={bulk_enrollment_job.uuid}'
                    f' braze_campaign_id={campaign_id} lms_user_id={bulk_enrollment_job.lms_user_id}'
                ),
                err_msg=(
                    f'failed _send_bulk_enrollment_results_email '
                    f'for bulk_enrollment_job_uuid={bulk_enrollment_job.uuid} '
                    f'braze_campaign_id={campaign_id} lms_user_id={bulk_enrollment_job.lms_user_id}'
                ),
                trigger_properties={
                    'enterprise_customer_slug': enterprise_customer.get('slug'),
                    'enterprise_customer_name': enterprise_customer.get('name'),
                    'bulk_enrollment_job_uuid': str(bulk_enrollment_job.uuid),
                },
            )
        elif settings.TRANSACTIONAL_MAIL_SERVICE == 'mailchimp':
            template_name = settings.MAILCHIMP_BULK_ENROLL_RESULT_TEMPLATE
            user_emails = []
            recipient_metadata = []
            for user in admin_users:
                if int(user['id']) != bulk_enrollment_job.lms_user_id:
                    continue
                user_emails.append({'email': user['email']})
                recipient_metadata.append({'rcpt': user['email'], 'values': {'email': user['email']}})
                break

            self._mailchimp_client.send_emails(
                template_name,
                merge_vars=[],
                global_merge_vars=[
                    {'name': 'enterprise_customer_slug', 'content': enterprise_customer.get('slug')},
                    {'name': 'enterprise_customer_name', 'content': enterprise_customer.get('name')},
                    {'name': 'bulk_enrollment_job_uuid', 'content': str(bulk_enrollment_job.uuid)},
                ],
                to_users=user_emails,
                subject=settings.MAILCHIMP_BULK_ENROLL_RESULT_SUBJECT,
                recipient_metadata=recipient_metadata,
                success_msg=(
                    'success _send_bulk_enrollment_results_email '
                    f'for bulk_enrollment_job_uuid={bulk_enrollment_job.uuid} '
                    f'template_name={template_name} lms_user_id={bulk_enrollment_job.lms_user_id}'
                ),
                err_msg=(
                    'failed _send_bulk_enrollment_results_email '
                    f'for bulk_enrollment_job_uuid={bulk_enrollment_job.uuid} '
                    f'template_name={template_name} lms_user_id={bulk_enrollment_job.lms_user_id}'
                )
            )

    def send_license_utilization_email(self, subscription, users, campaign_id, template_name, subject):
        """
        Sends email with properties required to detail license utilization.

        Arguments:
            subscription_details (dict): Dictionary containing subscription details in the format of
                {
                    'uuid': uuid,
                    'title': str,
                    'enterprise_customer_uuid': str,
                    'enterprise_customer_name': str,
                    'num_allocated_licenses': str,
                    'num_licenses': num,
                    'highest_utilization_threshold_reached': num
                }
            users (list of dict): List of users to send the emails to in the format of
                {
                    'lms_user_id': str,
                    'ecu_id': str,
                    'email': str,
                }
            campaign_id (str): braze campaign id
            template_name (str): Mailchimp template name
            subject (str): email subject for mailchimp
        """
        if not users:
            return

        subscription_uuid = subscription.uuid
        if settings.TRANSACTIONAL_MAIL_SERVICE == 'braze':
            trigger_properties = {
                'subscription_plan_title': subscription.title,
                'subscription_plan_expiration_date': datetime.strftime(subscription.expiration_date, '%b %-d, %Y'),
                'enterprise_customer_name': subscription.customer_agreement.enterprise_customer_name,
                'num_allocated_licenses': subscription.num_allocated_licenses,
                'num_licenses': subscription.num_licenses,
                'admin_portal_url': get_admin_portal_url(subscription.customer_agreement.enterprise_customer_slug),
                'num_auto_applied_licenses_since_turned_on': subscription.auto_applied_licenses_count_since(),
            }
            recipients = [
                {'external_user_id': user['lms_user_id'], 'trigger_properties': {'email': user['email']}}
                for user in users
            ]
            self._braze_client.send_emails(
                campaign_id,
                recipients,
                success_msg=(
                    f'sent {campaign_id} email for subscription {subscription_uuid} to {len(recipients)} admins.'
                ),
                err_msg=f'failed to send {campaign_id} email for subscription {subscription_uuid}.',
                trigger_properties=trigger_properties,
            )
        elif settings.TRANSACTIONAL_MAIL_SERVICE == 'mailchimp':
            template_context = [
                {'name': 'subscription_plan_title', 'content': subscription.title},
                {
                    'name': 'subscription_plan_expiration_date',
                    'content': datetime.strftime(subscription.expiration_date, '%b %-d, %Y'),
                },
                {
                    'name': 'enterprise_customer_name',
                    'content': subscription.customer_agreement.enterprise_customer_name,
                },
                {'name': 'num_allocated_licenses', 'content': subscription.num_allocated_licenses},
                {'name': 'num_licenses', 'content': subscription.num_licenses},
                {
                    'name': 'admin_portal_url',
                    'content': get_admin_portal_url(subscription.customer_agreement.enterprise_customer_slug),
                },
                {
                    'name': 'num_auto_applied_licenses_since_turned_on',
                    'content': subscription.auto_applied_licenses_count_since(),
                },
            ]

            recipients = []
            recipient_metadata = []
            for user in users:
                recipients.append({'email': user['email']})
                recipient_metadata.append({'rcpt': user['email'], 'values': {'email': user['email']}})
            self._mailchimp_client.send_emails(
                template_name,
                [],
                recipients,
                subject=subject,
                success_msg=(
                    f'sent {template_name} email for subscription {subscription_uuid} to {len(recipients)} admins.'
                ),
                err_msg=f'failed to send {template_name} email for subscription {subscription_uuid}.',
                recipient_metadata=recipient_metadata,
                global_merge_vars=template_context,
            )
