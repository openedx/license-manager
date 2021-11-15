import logging
from smtplib import SMTPException
from tempfile import NamedTemporaryFile
import csv
import os

from braze.client import BrazeClient
from celery import shared_task
from celery_utils.logged_task import LoggedTask
from django.conf import settings
from django.db import transaction
from django.utils.dateparse import parse_datetime

import license_manager.apps.subscriptions.api as subscriptions_api
from license_manager.apps.api import utils
from license_manager.apps.api.models import BulkEnrollmentJob
from license_manager.apps.api_client.braze import BrazeApiClient
from license_manager.apps.api_client.enterprise import EnterpriseApiClient
from license_manager.apps.subscriptions.constants import (
    NOTIFICATION_CHOICE_AND_CAMPAIGN_BY_THRESHOLD,
    PENDING_ACCOUNT_CREATION_BATCH_SIZE,
    REVOCABLE_LICENSE_STATUSES,
    WEEKLY_UTILIZATION_EMAIL_INTERLUDE,
    NotificationChoices,
)
from license_manager.apps.subscriptions.emails import (
    send_activation_emails,
    send_onboarding_email,
    send_revocation_cap_notification_email,
)
from license_manager.apps.subscriptions.models import (
    CustomerAgreement,
    License,
    Notification,
    SubscriptionPlan,
)
from license_manager.apps.subscriptions.utils import (
    chunks,
    get_enterprise_reply_to_email,
    get_enterprise_sender_alias,
    localized_utcnow,
)


logger = logging.getLogger(__name__)

# Soft time out of 15 minutes, max time out of 16 minutes
SOFT_TIME_LIMIT = 900
MAX_TIME_LIMIT = 960


@shared_task(base=LoggedTask, soft_time_limit=SOFT_TIME_LIMIT, time_limit=MAX_TIME_LIMIT)
def activation_email_task(custom_template_text, email_recipient_list, subscription_uuid):
    """
    Sends license activation email(s) asynchronously, and creates pending enterprise users to link the email recipients
    to the subscription's enterprise.

    Arguments:
        custom_template_text (dict): Dictionary containing `greeting` and `closing` keys to be used for customizing
            the email template.
        email_recipient_list (list of str): List of recipients to send the emails to.
        subscription_uuid (str): UUID (string representation) of the subscription that the recipients are associated
            with or will be associated with.
    """
    subscription_plan = SubscriptionPlan.objects.get(uuid=subscription_uuid)
    pending_licenses = subscription_plan.licenses.filter(user_email__in=email_recipient_list).order_by('uuid')
    subscription_plan_type = subscription_plan.plan_type.id if subscription_plan.plan_type else None
    enterprise_api_client = EnterpriseApiClient()
    enterprise_customer = enterprise_api_client.get_enterprise_customer_data(subscription_plan.enterprise_customer_uuid)
    enterprise_slug = enterprise_customer.get('slug')
    enterprise_name = enterprise_customer.get('name')
    enterprise_sender_alias = get_enterprise_sender_alias(enterprise_customer)
    reply_to_email = get_enterprise_reply_to_email(enterprise_customer)

    try:
        send_activation_emails(
            custom_template_text, pending_licenses, enterprise_slug, enterprise_name, enterprise_sender_alias,
            reply_to_email, subscription_plan_type,
        )
    except SMTPException:
        msg = 'License manager activation email sending received an exception for enterprise: {}.'.format(
            enterprise_name
        )
        logger.error(msg, exc_info=True)
        return


@shared_task(base=LoggedTask, soft_time_limit=SOFT_TIME_LIMIT, time_limit=MAX_TIME_LIMIT)
def link_learners_to_enterprise_task(learner_emails, enterprise_customer_uuid):
    """
    Links learners to an enterprise asynchronously.

    Arguments:
        learner_emails (list): list email addresses to link to the given enterprise.
        enterprise_customer_uuid (str): UUID (string representation) of the enterprise to link learns to.
    """
    enterprise_api_client = EnterpriseApiClient()

    for user_email_batch in chunks(learner_emails, PENDING_ACCOUNT_CREATION_BATCH_SIZE):
        enterprise_api_client.create_pending_enterprise_users(
            enterprise_customer_uuid,
            user_email_batch,
        )


@shared_task(base=LoggedTask, soft_time_limit=SOFT_TIME_LIMIT, time_limit=MAX_TIME_LIMIT)
def send_reminder_email_task(custom_template_text, email_recipient_list, subscription_uuid):
    """
    Sends license activation reminder email(s) asynchronously.

    Arguments:
        custom_template_text (dict): Dictionary containing `greeting` and `closing` keys to be used for customizing
            the email template.
        email_recipient_list (list of str): List of recipients to send the emails to.
        subscription_uuid (str): UUID (string representation) of the subscription that the recipients are associated
            with or will be associated with.
    """
    subscription_plan = SubscriptionPlan.objects.get(uuid=subscription_uuid)
    subscription_plan_type = subscription_plan.plan_type.id if subscription_plan.plan_type else None
    pending_licenses = subscription_plan.licenses.filter(user_email__in=email_recipient_list).order_by('uuid')
    enterprise_api_client = EnterpriseApiClient()
    enterprise_customer = enterprise_api_client.get_enterprise_customer_data(subscription_plan.enterprise_customer_uuid)
    enterprise_slug = enterprise_customer.get('slug')
    enterprise_name = enterprise_customer.get('name')
    enterprise_sender_alias = get_enterprise_sender_alias(enterprise_customer)
    reply_to_email = get_enterprise_reply_to_email(enterprise_customer)

    try:
        send_activation_emails(
            custom_template_text,
            pending_licenses,
            enterprise_slug,
            enterprise_name,
            enterprise_sender_alias,
            reply_to_email,
            subscription_plan_type,
            is_reminder=True
        )
    except SMTPException:
        msg = 'License manager reminder email sending received an exception for enterprise: {}.'.format(
            enterprise_name
        )
        logger.error(msg, exc_info=True)
        # Return without updating the last_remind_date for licenses
        return

    License.set_date_fields_to_now(pending_licenses, ['last_remind_date'])


@shared_task(base=LoggedTask)
def send_onboarding_email_task(enterprise_customer_uuid, user_email, subscription_plan_type):
    """
    Asynchronously sends onboarding email to learner. Intended for use following license activation.
    """
    try:
        send_onboarding_email(enterprise_customer_uuid, user_email, subscription_plan_type)
    except SMTPException:
        logger.error('Onboarding email to {} failed'.format(user_email), exc_info=True)


@shared_task(base=LoggedTask)
def send_auto_applied_license_email_task(enterprise_customer_uuid, user_email):
    """
    Asynchronously sends onboarding email to learner. Intended for use following automatic license activation.

    Uses Braze client to send email via Braze campaign.
    """
    try:
        # Get some info about the enterprise customer
        enterprise_api_client = EnterpriseApiClient()
        enterprise_customer = enterprise_api_client.get_enterprise_customer_data(enterprise_customer_uuid)
        enterprise_slug = enterprise_customer.get('slug')
        enterprise_name = enterprise_customer.get('name')
        learner_portal_search_enabled = enterprise_customer.get('enable_integrated_customer_learner_portal_search')
        identity_provider = enterprise_customer.get('identity_provider')
    except Exception:
        message = (
            f'Error getting data about the enterprise_customer {enterprise_customer_uuid}. '
            f'Onboarding email to {user_email} for auto applied license failed.'
        )
        logger.error(message, exc_info=True)
        return

    # Determine which email campaign to use
    if identity_provider and learner_portal_search_enabled is False:
        braze_campaign_id = settings.AUTOAPPLY_NO_LEARNER_PORTAL_CAMPAIGN
    else:
        braze_campaign_id = settings.AUTOAPPLY_WITH_LEARNER_PORTAL_CAMPAIGN

    # Form data we want to hand to the campaign's email template
    braze_trigger_properties = {
        'enterprise_customer_slug': enterprise_slug,
        'enterprise_customer_name': enterprise_name,
    }

    try:
        # Hit the Braze api to send the email
        braze_client_instance = BrazeApiClient()
        braze_client_instance.send_campaign_message(
            braze_campaign_id,
            emails=[user_email],
            trigger_properties=braze_trigger_properties,
        )

    except Exception:
        message = (
            'Error hitting Braze API. '
            f'Onboarding email to {user_email} for auto applied license failed.'
        )
        logger.error(message, exc_info=True)


@shared_task(base=LoggedTask, soft_time_limit=SOFT_TIME_LIMIT, time_limit=MAX_TIME_LIMIT)
def revoke_course_enrollments_for_user_task(user_id, enterprise_id):
    """
    Sends revoking the user's enterprise licensed course enrollments asynchronously

    Arguments:
        user_id (str): The ID of the user who had an enterprise license revoked
        enterprise_id (str): The ID of the enterprise to revoke course enrollments for
    """
    try:
        enterprise_api_client = EnterpriseApiClient()
        enterprise_api_client.revoke_course_enrollments_for_user(user_id=user_id, enterprise_id=enterprise_id)
        logger.info(
            'Revocation of course enrollments SUCCEEDED for user [{user_id}], enterprise [{enterprise_id}]'.format(
                user_id=user_id,
                enterprise_id=enterprise_id,
            )
        )
    except Exception:  # pylint: disable=broad-except
        logger.error(
            'Revocation of course enrollments FAILED for user [{user_id}], enterprise [{enterprise_id}]'.format(
                user_id=user_id,
                enterprise_id=enterprise_id,
            ),
            exc_info=True,
        )


@shared_task(base=LoggedTask, soft_time_limit=SOFT_TIME_LIMIT, time_limit=MAX_TIME_LIMIT)
def license_expiration_task(license_uuids, ignore_enrollments_modified_after=None):
    """
    Sends terminating the licensed course enrollments for the submitted license_uuids asynchronously

    Arguments:
        license_uuids (list of str): The UUIDs of the expired licenses
    """
    try:
        enterprise_api_client = EnterpriseApiClient()
        enterprise_api_client.bulk_licensed_enrollments_expiration(
            expired_license_uuids=license_uuids,
            ignore_enrollments_modified_after=ignore_enrollments_modified_after
        )
        logger.info(
            "Expiration of course enrollments SUCCEEDED for licenses [{license_uuids}]".format(
                license_uuids=license_uuids,
            )
        )
    except Exception as exc:
        logger.error(
            "Expiration of course enrollments FAILED for licenses [{license_uuids}]".format(
                license_uuids=license_uuids,
            ),
            exc_info=True,
        )
        raise exc


@shared_task(base=LoggedTask)
def send_revocation_cap_notification_email_task(subscription_uuid):
    """
    Sends revocation cap email notification to ECS asynchronously.

    Arguments:
        subscription_uuid (str): UUID (string representation) of the subscription that has reached its recovation cap.
    """
    subscription_plan = SubscriptionPlan.objects.get(uuid=subscription_uuid)
    enterprise_api_client = EnterpriseApiClient()
    enterprise_customer = enterprise_api_client.get_enterprise_customer_data(subscription_plan.enterprise_customer_uuid)
    enterprise_name = enterprise_customer.get('name')
    enterprise_sender_alias = get_enterprise_sender_alias(enterprise_customer)
    reply_to_email = get_enterprise_reply_to_email(enterprise_customer)

    try:
        send_revocation_cap_notification_email(
            subscription_plan,
            enterprise_name,
            enterprise_sender_alias,
            reply_to_email,
        )
    except SMTPException:
        logger.error('Revocation cap notification email sending received an exception.', exc_info=True)


@shared_task(base=LoggedTask)
def revoke_all_licenses_task(subscription_uuid):
    """
    Revokes all licenses associated with a subscription plan.

    Arguments:
        subscription_uuid (str): UUID (string representation) of the subscription to revoke all licenses for.
    """
    subscription_plan = SubscriptionPlan.objects.get(uuid=subscription_uuid)

    with transaction.atomic():
        subscription_licenses = subscription_plan.licenses.filter(
            status__in=REVOCABLE_LICENSE_STATUSES,
        )

        revocation_results = []

        for sl in subscription_licenses:
            try:
                revocation_results.append(subscriptions_api.revoke_license(sl))
            except Exception:
                logger.error('Could not revoke license with uuid {} during revoke_all_licenses_task'.format(sl.uuid),
                             exc_info=True)
                raise

    for result in revocation_results:
        subscriptions_api.execute_post_revocation_tasks(**result)


def _send_bulk_enrollment_results_email(
    bulk_enrollment_job,
    campaign_id,
):
    """
    Sends email with properties required to detail the results of a bulk enrollment job.

    Arguments:
        bulk_enrollment_job (BulkEnrollmentJob): the completed bulk enrollment job
        campaign_id: (str): The Braze campaign identifier

    """
    emails = []
    try:

        enterprise_api_client = EnterpriseApiClient()
        enterprise_customer = enterprise_api_client.get_enterprise_customer_data(
            bulk_enrollment_job.enterprise_customer_uuid,
        )

        User = get_user_model()
        user = User.objects.get(id=bulk_enrollment_job.lms_user_id)

        emails = [user.email]

        braze_client = BrazeApiClient()
        braze_client.send_campaign_message(
            campaign_id,
            emails=emails,
            trigger_properties={
                'enterprise_customer_slug': enterprise_customer.get('slug'),
                'enterprise_customer_name': enterprise_customer.get('name'),
                'bulk_enrollment_job_uuid': bulk_enrollment_job.uuid,
            }
        )
        msg = f'Sent {campaign_id} email for BulkEnrollmentJob result {bulk_enrollment_job.uuid} to {len(emails)} admins.'
        logger.info(msg)
    except Exception as ex:
        msg = f'Failed to send {campaign_id} email for BulkEnrollmentJob result {bulk_enrollment_job.uuid} to {len(emails)} admins.'
        logger.error(msg, exc_info=True)
        raise ex

@shared_task(base=LoggedTask)
def enterprise_enrollment_license_subsidy_task(bulk_enrollment_job_uuid, enterprise_customer_uuid, learner_emails, course_run_keys, notify_learners, subscription_uuid=None):
    """
    Enroll a list of enterprise learners into a list of course runs with or without notifying them. Optionally, filter license check by a specific subscription.

    Arguments:
        bulk_enrollment_job_uuid (str): UUID (string representation) for a BulkEnrollmentJob created by the enqueuing process for logging and progress tracking table updates.
        enterprise_customer_uuid (str): UUID (string representation) the enterprise customer id
        learner_emails (list(str)): email addresses of the learners to enroll
        course_run_keys (list(str)): course keys of the courses to enroll the learners into
        notify_learners (bool): whether or not to send notifications of their enrollment to the learners
        subscription_uuid (str): UUID (string representation) of the specific enterprise subscription to use when validating learner licenses
    """
    logger.info("starting bulk_enrollment_job_uuid={} enterprise_enrollment_license_subsidy_task for enterprise_customer_uuid={}".format(bulk_enrollment_job_uuid, enterprise_customer_uuid))

    # collect/return results (rather than just write to the CSV) to help testability
    results = []

    bulk_enrollment_job = BulkEnrollmentJob.objects.get(pk=bulk_enrollment_job_uuid)
    customer_agreement = CustomerAgreement.objects.get(enterprise_customer_uuid=enterprise_customer_uuid)

    # this is to avoid hitting timeouts on the enterprise enroll api
    # take course keys 25 at a time, for each course key chunk, take learners 25 at a time
    for course_run_key_batch in chunks(course_run_keys, 25):
        logger.debug("enterprise_customer_uuid={} course_run_key_batch size: {}".format(enterprise_customer_uuid, len(course_run_key_batch)))
        for learner_enrollment_batch in chunks(learner_emails, 25):
            logger.debug("enterprise_customer_uuid={} learner_enrollment_batch size: {}".format(enterprise_customer_uuid, len(learner_enrollment_batch)))

            missing_subscriptions, licensed_enrollment_info = utils.check_missing_licenses(customer_agreement,
                                                                                           learner_enrollment_batch,
                                                                                           course_run_key_batch,
                                                                                           subscription_uuid
                                                                                           )

            if missing_subscriptions:
                for failed_email in missing_subscriptions.keys():
                    for course_key in missing_subscriptions[failed_email]:
                        results.append([failed_email, course_key, 'failed', 'missing subscription'])

            if licensed_enrollment_info:
                options = {
                    'licenses_info': licensed_enrollment_info,
                    'notify': notify_learners
                }
                enrollment_result = EnterpriseApiClient().bulk_enroll_enterprise_learners(
                    str(enterprise_customer_uuid), options
                ).json()

                for success in enrollment_result['successes']:
                    results.append([success.get('email'), success.get('course_run_key'), 'success', ''])

                for pending in enrollment_result['pending']:
                    results.append([pending.get('email'), pending.get('course_run_key'), 'pending', 'pending license activation'])

                for failure in enrollment_result['failures']:
                    results.append([failure.get('email'), failure.get('course_run_key'), 'failed', ''])

                if enrollment_result.get('invalid_email_addresses'):
                    for result_email in enrollment_result['invalid_email_addresses']:
                        for course_key in course_run_key_batch:
                            results.append([result_email, course_key, 'failed', 'invalid email address'])


    result_file = NamedTemporaryFile(mode='w', delete=False)
    try:
        result_writer = csv.writer(result_file)
        result_writer.writerow(['email address', 'course key', 'enrollment status', 'notes'])
        for result in results:
            result_writer.writerow(result)

        result_file.close()
        # TODO would normally feature gate this
        # _send_bulk_enrollment_results_email(
        #     bulk_enrollment_job=bulk_enrollment_job,
        #     campaign_id=settings.BULK_ENROLL_RESULT_CAMPAIGN,
        # )
    finally:
        result_file.close()
        os.unlink(result_file.name)

    return results


def _send_license_utilization_email(
    subscription_details,
    campaign_id,
    emails
):
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
        campaign_id: (str): The Braze campaign identifier
        emails: (list of str): List of recipients to send the email to

    """

    subscription_uuid = subscription_details['uuid']
    try:
        braze_client = BrazeApiClient()
        braze_client.send_campaign_message(
            campaign_id,
            emails=emails,
            trigger_properties={
                'subscription_plan_title': subscription_details['title'],
                'enterprise_customer_name': subscription_details['enterprise_customer_name'],
                'num_allocated_licenses': subscription_details['num_allocated_licenses'],
                'num_licenses': subscription_details['num_licenses']
            }
        )
        msg = f'Sent {campaign_id} email for subscription {subscription_uuid} to {len(emails)} admins.'
        logger.info(msg)
    except Exception as ex:
        msg = f'Failed to send {campaign_id} email for subscription {subscription_uuid} to {len(emails)} admins.'
        logger.error(msg, exc_info=True)
        raise ex


@shared_task(base=LoggedTask, soft_time_limit=SOFT_TIME_LIMIT, time_limit=MAX_TIME_LIMIT)
def send_weekly_utilization_email_task(subscription_details, recipients):
    """
    Sends email to admins detailing license utilization for a subscription plan.

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
        recipients (list of dict): List of recipients to send the emails to in the format of
            {
                'ecu_id': str,
                'email': str,
                'created': str
            }
    """
    if not recipients:
        return

    now = localized_utcnow()
    emails = []

    with transaction.atomic():

        # determine eligibility for weekly email
        for recipient in recipients:
            activation_date = parse_datetime(recipient['created'])

            user_is_eligible = (now - activation_date).days >= WEEKLY_UTILIZATION_EMAIL_INTERLUDE

            if not user_is_eligible:
                continue

            notification, created = Notification.objects.get_or_create(
                enterprise_customer_uuid=subscription_details['enterprise_customer_uuid'],
                enterprise_customer_user_uuid=recipient['ecu_id'],
                subscripton_plan_id=subscription_details['uuid'],
                notification_type=NotificationChoices.PERIODIC_INFORMATIONAL
            )

            user_has_not_received_email_for_week = created or (now - notification.last_sent).days >= WEEKLY_UTILIZATION_EMAIL_INTERLUDE

            if user_has_not_received_email_for_week:
                emails.append(recipient['email'])
                notification.last_sent = now
                notification.save()

        if emails:
            # will raise exception and roll back changes if error occurs
            _send_license_utilization_email(
                subscription_details=subscription_details,
                campaign_id=settings.WEEKLY_LICENSE_UTILIZATION_CAMPAIGN,
                emails=emails
            )


@shared_task(base=LoggedTask, soft_time_limit=SOFT_TIME_LIMIT, time_limit=MAX_TIME_LIMIT)
def send_utilization_threshold_reached_email_task(subscription_details, recipients):
    """
    Sends email to admins if a license utilization threshold for a subscription plan has been reached.

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
        recipients (list of dict): List of recipients to send the emails to in the format of
            {
                'ecu_id': str,
                'email': str,
                'created': str
            }
    """

    if not recipients:
        return

    # only send email for the highest threshold reached
    highest_utilization_threshold_reached = subscription_details['highest_utilization_threshold_reached']
    if highest_utilization_threshold_reached is not None:
        emails = []

        notification_type, campaign = NOTIFICATION_CHOICE_AND_CAMPAIGN_BY_THRESHOLD[highest_utilization_threshold_reached]

        with transaction.atomic():
            for recipient in recipients:
                _, created = Notification.objects.get_or_create(
                    enterprise_customer_uuid=subscription_details['enterprise_customer_uuid'],
                    enterprise_customer_user_uuid=recipient['ecu_id'],
                    subscripton_plan_id=subscription_details['uuid'],
                    notification_type=notification_type
                )

                # created means the email for this threshold has not been sent yet
                if created:
                    emails.append(recipient['email'])
            if emails:
                # will raise exception and roll back changes if error occurs
                _send_license_utilization_email(
                    subscription_details=subscription_details,
                    campaign_id=getattr(settings, campaign),
                    emails=emails
                )
