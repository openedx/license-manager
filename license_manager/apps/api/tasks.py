import csv
import logging
import uuid
from datetime import datetime
from tempfile import NamedTemporaryFile

from braze.exceptions import BrazeClientError
from celery import shared_task
from celery_utils.logged_task import LoggedTask
from django.conf import settings
from django.db import IntegrityError, transaction
from django.db.utils import OperationalError
from mailchimp_transactional.api_client import \
    ApiClientError as MailChimpClientError
from requests.exceptions import ConnectionError as RequestsConnectionError
from requests.exceptions import HTTPError
from requests.exceptions import JSONDecodeError as RequestsJSONDecodeError
from requests.exceptions import Timeout as RequestsTimeoutError

import license_manager.apps.subscriptions.api as subscriptions_api
from license_manager.apps.api import utils
from license_manager.apps.api.email import EmailClient
from license_manager.apps.api.models import BulkEnrollmentJob
from license_manager.apps.api_client.braze import BrazeApiClient
from license_manager.apps.api_client.enterprise import EnterpriseApiClient
from license_manager.apps.subscriptions.constants import (
    ACTIVATED,
    ASSIGNMENT_EMAIL_BATCH_SIZE,
    DAYS_BEFORE_INITIAL_UTILIZATION_EMAIL_SENT,
    ENTERPRISE_BRAZE_ALIAS_LABEL,
    LICENSE_UTILIZATION_THRESHOLDS,
    NOTIFICATION_CHOICE_AND_CAMPAIGN_BY_THRESHOLD,
    PENDING_ACCOUNT_CREATION_BATCH_SIZE,
    REMINDER_EMAIL_BATCH_SIZE,
    REVOCABLE_LICENSE_STATUSES,
    TRACK_LICENSE_CHANGES_BATCH_SIZE,
    NOTIFY_EMAIL_ACTION_TYPE,
    REMIND_EMAIL_ACTION_TYPE,
    NotificationChoices,
)
from license_manager.apps.subscriptions.event_utils import track_license_changes
from license_manager.apps.subscriptions.models import (
    CustomerAgreement,
    License,
    Notification,
    SubscriptionPlan,
)
from license_manager.apps.subscriptions.utils import chunks, localized_utcnow


logger = logging.getLogger(__name__)

# Soft time out of 15 minutes, max time out of 16 minutes
SOFT_TIME_LIMIT = 900
MAX_TIME_LIMIT = 960

LICENSE_DEBUG_PREFIX = '[LICENSE DEBUGGING]'


class LoggedTaskWithRetry(LoggedTask):  # pylint: disable=abstract-method
    """
    Shared base task that allows tasks that raise some common exceptions to retry automatically.

    See https://docs.celeryproject.org/en/stable/userguide/tasks.html#automatic-retry-for-known-exceptions for
    more documentation.
    """
    autoretry_for = (
        RequestsConnectionError,
        RequestsTimeoutError,
        IntegrityError,
        OperationalError,
        BrazeClientError,
        MailChimpClientError,
        HTTPError,
    )
    retry_kwargs = {'max_retries': 3}
    # Use exponential backoff for retrying tasks
    # see https://docs.celeryq.dev/en/stable/userguide/tasks.html#Task.retry_backoff
    # First retry will delay 60 seconds, second will delay 120 seconds, third 240 seconds.
    retry_backoff = 60
    # Add randomness to backoff delays to prevent all tasks in queue from executing simultaneously.
    # The actual delay value will be a random number in the range (0, retry_backoff)
    retry_jitter = True


@shared_task(base=LoggedTaskWithRetry, soft_time_limit=SOFT_TIME_LIMIT, time_limit=MAX_TIME_LIMIT)
def create_braze_aliases_task(user_emails):
    """
    Creates a Braze alias for each email using the ENTERPRISE_BRAZE_ALIAS_LABEL.
    A Braze alias must be created when sending emails to anonymous users.

    Arguments:
        user_emails (list of str): List of emails to create aliases for.

    """
    try:
        braze_client_instance = BrazeApiClient(logger_prefix=LICENSE_DEBUG_PREFIX)
        braze_client_instance.create_braze_alias(
            user_emails,
            ENTERPRISE_BRAZE_ALIAS_LABEL,
        )
    except BrazeClientError as exc:
        logger.exception(exc)
        raise exc


@shared_task(base=LoggedTaskWithRetry, soft_time_limit=SOFT_TIME_LIMIT, time_limit=MAX_TIME_LIMIT)
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


def _batch_notify_or_remind_assigned_emails(
    custom_template_text,
    email_recipient_list,
    subscription_uuid,
    allowed_batch_size,
    action_type,
):
    """
    Does the work of sending notification and reminder emails
    for assigned licenses.

    Params:
      custom_template_text (dict): Dictionary containing `greeting` and `closing` keys
        to be used for customizing the email template.
      email_recipient_list (list of str): List of recipients to send the emails to.
      subscription_uuid (str): UUID string of the subscription plan that the
        recipients are (or will be) associated with.
      allowed_batch_size (int): Maximum number of recipients (really their associated assigned licenses)
        which can be processed in a single call to this method.
      action_type (str): A string used in logging messages to indicate which type of notification
        is being sent and determine template for email.
    """
    subscription_plan = SubscriptionPlan.objects.get(uuid=subscription_uuid)
    pending_licenses = subscription_plan.assigned_licenses.filter(
        user_email__in=email_recipient_list,
    ).order_by('uuid')

    if len(pending_licenses) > allowed_batch_size:
        raise Exception(f'Found more than {allowed_batch_size} licenses, no email sent to {action_type}')

    enterprise_api_client = EnterpriseApiClient()
    enterprise_customer = enterprise_api_client.get_enterprise_customer_data(
        subscription_plan.enterprise_customer_uuid,
    )

    email_client = EmailClient()
    pending_license_by_email = email_client.send_assignment_or_reminder_email(
        pending_licenses,
        enterprise_customer,
        custom_template_text,
        action_type,
    )

    emails_with_no_assignments = [
        _email for _email in email_recipient_list
        if _email not in pending_license_by_email
    ]
    if emails_with_no_assignments:
        logger.warning(f'{LICENSE_DEBUG_PREFIX} No {action_type} email sent for {emails_with_no_assignments}')

    return pending_licenses


@shared_task(base=LoggedTaskWithRetry, soft_time_limit=SOFT_TIME_LIMIT, time_limit=MAX_TIME_LIMIT)
def send_assignment_email_task(custom_template_text, email_recipient_list, subscription_uuid):
    """
    Sends license assignment email(s) asynchronously.

    Arguments:
        custom_template_text (dict): Dictionary containing `greeting` and `closing` keys to be used for customizing
            the email template.
        email_recipient_list (list of str): List of recipients to send the emails to.
        subscription_uuid (str): UUID (string representation) of the subscription that the recipients are associated
            with or will be associated with.
    """
    _batch_notify_or_remind_assigned_emails(
        custom_template_text,
        email_recipient_list,
        subscription_uuid,
        ASSIGNMENT_EMAIL_BATCH_SIZE,
        NOTIFY_EMAIL_ACTION_TYPE,
    )


@shared_task(base=LoggedTaskWithRetry, soft_time_limit=SOFT_TIME_LIMIT, time_limit=MAX_TIME_LIMIT)
def send_reminder_email_task(custom_template_text, email_recipient_list, subscription_uuid):
    """
    Sends license activation reminder email(s) asynchronously.

    Arguments:
        custom_template_text (dict): Dictionary containing `greeting` and `closing` keys to be used for customizing
            the email template.
        email_recipient_list (list of str): List of recipients to send the emails to.
        subscription_uuid (str): UUID (string representation) of the subscription that the recipients are associated
            with or will be associated with.
    Raises:
      An exception if the number of assigned licenses to send reminders for exceeds the max
      allowed request size of the Braze campaign endpoint.
    """
    pending_licenses = _batch_notify_or_remind_assigned_emails(
        custom_template_text,
        email_recipient_list,
        subscription_uuid,
        REMINDER_EMAIL_BATCH_SIZE,
        REMIND_EMAIL_ACTION_TYPE,
    )
    License.set_date_fields_to_now(pending_licenses, ['last_remind_date'])


@shared_task(base=LoggedTaskWithRetry)
def send_post_activation_email_task(enterprise_customer_uuid, user_email):
    """
    Asynchronously sends post license activation email to learner.
    """
    enterprise_customer = EnterpriseApiClient().get_enterprise_customer_data(enterprise_customer_uuid)
    EmailClient().send_post_activation_email(enterprise_customer, user_email)


@shared_task(base=LoggedTaskWithRetry)
def send_auto_applied_license_email_task(enterprise_customer_uuid, user_email):
    """
    Asynchronously sends onboarding email to learner. Intended for use following automatic license activation.

    Uses Braze client to send email via Braze campaign.
    """
    try:
        enterprise_api_client = EnterpriseApiClient()
        enterprise_customer = enterprise_api_client.get_enterprise_customer_data(enterprise_customer_uuid)
    except Exception:  # pylint: disable=broad-except
        message = (
            f'Error getting data about the enterprise_customer {enterprise_customer_uuid}. '
        )
        logger.error(message, exc_info=True)
        return
    EmailClient().send_auto_applied_license_email(enterprise_customer, user_email)


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


def execute_post_revocation_tasks(revoked_license, original_status):
    """
    Executes a set of tasks after a license has been revoked.

    Tasks:
        - Revoke enrollments if the License has an original status of ACTIVATED.
        - Send email notification to ECS if the Subscription Plan has reached its revocation cap.
    """

    # We should only need to revoke enrollments if the License has an original
    # status of ACTIVATED, pending users shouldn't have any enrollments.
    if original_status == ACTIVATED:
        revoke_course_enrollments_for_user_task.delay(
            user_id=revoked_license.lms_user_id,
            enterprise_id=str(revoked_license.subscription_plan.enterprise_customer_uuid),
        )

    if not revoked_license.subscription_plan.has_revocations_remaining:
        # Send email notification to ECS that the Subscription Plan has reached its revocation cap
        send_revocation_cap_notification_email_task.delay(
            subscription_uuid=revoked_license.subscription_plan.uuid,
        )

    logger.info('License {} has been revoked'.format(revoked_license.uuid))


@shared_task(base=LoggedTaskWithRetry, soft_time_limit=SOFT_TIME_LIMIT, time_limit=MAX_TIME_LIMIT)
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


@shared_task(base=LoggedTaskWithRetry)
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

    now = localized_utcnow()
    revocation_date = datetime.strftime(now, "%B %d, %Y, %I:%M%p %Z")
    EmailClient().send_revocation_cap_notification_email(subscription_plan, enterprise_name, revocation_date)


@shared_task(base=LoggedTaskWithRetry)
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
        execute_post_revocation_tasks(**result)


def _send_bulk_enrollment_results_email(bulk_enrollment_job):
    """
    Sends email with properties required to detail the results of a bulk enrollment job.

    Arguments:
        bulk_enrollment_job (BulkEnrollmentJob): the completed bulk enrollment job

    """
    enterprise_api_client = EnterpriseApiClient()
    enterprise_customer = enterprise_api_client.get_enterprise_customer_data(
        bulk_enrollment_job.enterprise_customer_uuid,
    )
    admin_users = enterprise_api_client.get_enterprise_admin_users(
        bulk_enrollment_job.enterprise_customer_uuid,
    )
    EmailClient().send_bulk_enrollment_results_email(enterprise_customer, bulk_enrollment_job, admin_users)


@shared_task(base=LoggedTask, soft_time_limit=SOFT_TIME_LIMIT, time_limit=MAX_TIME_LIMIT)
def enterprise_enrollment_license_subsidy_task(
    bulk_enrollment_job_uuid,
    enterprise_customer_uuid,
    learner_emails,
    course_run_keys,
    notify_learners,
    subscription_uuid,
):
    """
    Enroll a list of enterprise learners into a list of course runs with or without notifying them.
    Optionally, filter license check by a specific subscription.

    Arguments:
        bulk_enrollment_job_uuid (str): UUID (string representation) for a BulkEnrollmentJob created
            by the enqueuing process for logging and progress tracking table updates.
        enterprise_customer_uuid (str): UUID (string representation) the enterprise customer id
        learner_emails (list(str)): email addresses of the learners to enroll
        course_run_keys (list(str)): course keys of the courses to enroll the learners into
        notify_learners (bool): whether or not to send notifications of their enrollment to the learners
        subscription_uuid (str): UUID (string representation) of the specific enterprise subscription to use when
            validating learner licenses
    """
    # AED 2022-01-24 - I don't have enough context to unwind this sanely.
    # Declaring bankruptcy for now.
    # pylint: disable=too-many-nested-blocks
    try:
        logger.info(
            'starting enterprise_enrollment_license_subsidy_task for '
            f'bulk_enrollment_job_uuid={bulk_enrollment_job_uuid} '
            f'enterprise_customer_uuid={enterprise_customer_uuid}'
        )

        # collect/return results (rather than just write to the CSV) to help testability
        results = []

        bulk_enrollment_job = BulkEnrollmentJob.objects.get(uuid=bulk_enrollment_job_uuid)
        customer_agreement = CustomerAgreement.objects.get(enterprise_customer_uuid=enterprise_customer_uuid)

        # this is to avoid hitting timeouts on the enterprise enroll api
        # take course keys 25 at a time, for each course key chunk, take learners 25 at a time
        for course_run_key_batch in chunks(course_run_keys, 25):
            logger.debug("enterprise_customer_uuid={} course_run_key_batch size: {}".format(
                enterprise_customer_uuid, len(course_run_key_batch)
            ))
            for learner_enrollment_batch in chunks(learner_emails, 25):
                logger.debug("enterprise_customer_uuid={} learner_enrollment_batch size: {}".format(
                    enterprise_customer_uuid, len(learner_enrollment_batch)
                ))

                missing_subscriptions, licensed_enrollment_info = utils.check_missing_licenses(
                    customer_agreement,
                    learner_enrollment_batch,
                    course_run_key_batch,
                    subscription_uuid=subscription_uuid,
                )

                if missing_subscriptions:
                    for failed_email, course_keys in missing_subscriptions.items():
                        for course_key in course_keys:
                            results.append([failed_email, course_key, 'failed', 'missing subscription'])

                if licensed_enrollment_info:
                    options = {
                        'licenses_info': licensed_enrollment_info,
                        'notify': notify_learners
                    }
                    enrollment_response = EnterpriseApiClient().bulk_enroll_enterprise_learners(
                        str(enterprise_customer_uuid), options
                    )
                    try:
                        enrollment_result = enrollment_response.json()
                    except RequestsJSONDecodeError:
                        logger.error(
                            f'Error in bulk license enrollment for {enterprise_customer_uuid}, '
                            f'response payload = {enrollment_response.content}'
                        )
                        raise

                    for success in enrollment_result['successes']:
                        results.append([success.get('email'), success.get('course_run_key'), 'success', ''])

                    for pending in enrollment_result['pending']:
                        results.append([
                            pending.get('email'), pending.get('course_run_key'),
                            'pending', 'pending license activation'
                        ])

                    for failure in enrollment_result['failures']:
                        results.append([failure.get('email'), failure.get('course_run_key'), 'failed', ''])

                    if enrollment_result.get('invalid_email_addresses'):
                        for result_email in enrollment_result['invalid_email_addresses']:
                            for course_key in course_run_key_batch:
                                results.append([result_email, course_key, 'failed', 'invalid email address'])

        with NamedTemporaryFile(mode='w', delete=False) as result_file:
            result_writer = csv.writer(result_file)
            result_writer.writerow(['email address', 'course key', 'enrollment status', 'notes'])
            for result in results:
                result_writer.writerow(result)

            result_file.close()

            if hasattr(settings, "BULK_ENROLL_JOB_AWS_BUCKET") and settings.BULK_ENROLL_JOB_AWS_BUCKET:
                bulk_enrollment_job.upload_results(result_file.name)

            if hasattr(settings, "BULK_ENROLL_RESULT_CAMPAIGN") and settings.BULK_ENROLL_RESULT_CAMPAIGN:
                _send_bulk_enrollment_results_email(bulk_enrollment_job=bulk_enrollment_job)

        return results
    except Exception as ex:
        msg = (
            'failed enterprise_enrollment_license_subsidy_task for '
            f'bulk_enrollment_job_uuid={bulk_enrollment_job_uuid} '
            f'enterprise_customer_uuid={enterprise_customer_uuid}'
        )
        logger.error(msg, exc_info=True)
        raise ex


def _get_admin_users_for_enterprise(enterprise_customer_uuid):
    api_client = EnterpriseApiClient()
    admin_users = api_client.get_enterprise_admin_users(enterprise_customer_uuid)
    return [
        {
            'lms_user_id': admin_user['id'],
            'ecu_id': admin_user['ecu_id'],
            'email': admin_user['email']
        }
        for admin_user in admin_users
    ]


@shared_task(base=LoggedTaskWithRetry, soft_time_limit=SOFT_TIME_LIMIT, time_limit=MAX_TIME_LIMIT)
def send_initial_utilization_email_task(subscription_uuid):
    """
    Sends email to admins detailing license utilization for a subscription plan after the initial week.

    Arguments:
        subscription_uuid (str): The subscription plan's uuid
    """

    subscription = SubscriptionPlan.objects.get(uuid=subscription_uuid)

    # check if the email has been sent for the subscription plan already
    # we only want to send this email once for any given plan
    has_email_been_sent_before = Notification.objects.filter(
        subscripton_plan_id=subscription.uuid,
        notification_type=NotificationChoices.PERIODIC_INFORMATIONAL
    ).count() > 0

    if has_email_been_sent_before:
        return

    # get the date when the subscription was last turned on
    auto_apply_licenses_turned_on_at = subscription.auto_apply_licenses_turned_on_at
    now = localized_utcnow()
    is_email_ready = (now - auto_apply_licenses_turned_on_at).days >= DAYS_BEFORE_INITIAL_UTILIZATION_EMAIL_SENT
    if not is_email_ready:
        return

    admin_users = _get_admin_users_for_enterprise(subscription.customer_agreement.enterprise_customer_uuid)

    with transaction.atomic():
        for admin_user in admin_users:
            notification = Notification.objects.create(
                enterprise_customer_uuid=subscription.customer_agreement.enterprise_customer_uuid,
                enterprise_customer_user_uuid=admin_user['ecu_id'],
                subscripton_plan_id=subscription.uuid,
                notification_type=NotificationChoices.PERIODIC_INFORMATIONAL
            )
            notification.save()

        # will raise exception and roll back changes if error occurs
        EmailClient().send_license_utilization_email(
            subscription=subscription,
            users=admin_users,
            campaign_id=settings.INITIAL_LICENSE_UTILIZATION_CAMPAIGN,
            template_name=settings.MAILCHIMP_INITIAL_LICENSE_UTILIZATION_TEMPLATE,
            subject=settings.MAILCHIMP_INITIAL_LICENSE_UTILIZATION_SUBJECT,
        )


@shared_task(base=LoggedTaskWithRetry, soft_time_limit=SOFT_TIME_LIMIT, time_limit=MAX_TIME_LIMIT)
def send_utilization_threshold_reached_email_task(subscription_uuid):
    """
    Sends email to admins if a license utilization threshold for a subscription plan has been reached.

    Arguments:
        subscription_uuid (str): The subscription plan's uuid
    """
    subscription = SubscriptionPlan.objects.get(uuid=subscription_uuid)

    # only send email for the highest threshold reached
    highest_utilization_threshold_reached = subscription.highest_utilization_threshold_reached
    if highest_utilization_threshold_reached is not None:

        notification_type, campaign, template, subject = NOTIFICATION_CHOICE_AND_CAMPAIGN_BY_THRESHOLD[
            highest_utilization_threshold_reached
        ]

        # check if we have already sent an email for the current threshold or any higher thresholds
        # if we sent an email for 100% utilization reached and a license was revoked, we don't want to send an email
        # when 75% utilization is reached
        current_and_higher_thresholds = [
            threshold for threshold in LICENSE_UTILIZATION_THRESHOLDS
            if threshold >= highest_utilization_threshold_reached
        ]
        current_and_higher_thresholds_notification_choices = [
            NOTIFICATION_CHOICE_AND_CAMPAIGN_BY_THRESHOLD[threshold][0] for threshold in current_and_higher_thresholds
        ]

        has_email_been_sent_before = Notification.objects.filter(
            enterprise_customer_uuid=subscription.customer_agreement.enterprise_customer_uuid,
            subscripton_plan_id=subscription.uuid,
            notification_type__in=current_and_higher_thresholds_notification_choices
        ).count() > 0

        if has_email_been_sent_before:
            message = (
                'Not sending utilization threshold reached email for {subscription.uuid}, '
                'email has already been sent previously.'
            )
            logger.info(message)
            return

        admin_users = _get_admin_users_for_enterprise(subscription.customer_agreement.enterprise_customer_uuid)
        with transaction.atomic():
            for admin_user in admin_users:
                Notification.objects.create(
                    enterprise_customer_uuid=subscription.customer_agreement.enterprise_customer_uuid,
                    enterprise_customer_user_uuid=admin_user['ecu_id'],
                    subscripton_plan_id=subscription.uuid,
                    notification_type=notification_type
                )

            # will raise exception and roll back changes if error occurs
            EmailClient().send_license_utilization_email(
                subscription=subscription,
                users=admin_users,
                campaign_id=getattr(settings, campaign),
                template_name=getattr(settings, template),
                subject=getattr(settings, subject),
            )


@shared_task(base=LoggedTaskWithRetry, soft_time_limit=SOFT_TIME_LIMIT, time_limit=MAX_TIME_LIMIT, bind=True)
def track_license_changes_task(self, license_uuids, event_name, properties=None, is_batch_assignment=False):
    """
    Calls ``track_license_changes()`` on some chunks of licenses.

    Args:
        license_uuid (list): List of license uuids
        event_name (str): Name of the event in the format of:
            edx.server.license-manager.license-lifecycle.<new-status>, see constants.SegmentEvents
        properties: (dict): Additional properties to track for each event,
            overrides fields from get_license_tracking_properties
    Returns:
        None
    """
    properties = properties or {}
    # We chunk these up as to not fetch too many license records from the DB in a single query.
    # We're also limited in `track_license_changes` by the number of records
    # this braze endpoint allows us to request at a time:
    # https://www.braze.com/docs/api/endpoints/export/user_data/post_users_identifier/
    for uuid_str_chunk in chunks(license_uuids, TRACK_LICENSE_CHANGES_BATCH_SIZE):
        license_uuid_chunk = [uuid.UUID(uuid_str) for uuid_str in uuid_str_chunk]
        licenses = License.objects.filter(uuid__in=license_uuid_chunk)
        track_license_changes(licenses, event_name, properties, is_batch_assignment)
        logger.info('Task {} tracked license changes for license uuids {}'.format(
            self.request.id,
            license_uuid_chunk,
        ))


@shared_task(base=LoggedTaskWithRetry, soft_time_limit=SOFT_TIME_LIMIT, time_limit=MAX_TIME_LIMIT)
def update_user_email_for_licenses_task(lms_user_id, new_email):
    """
    Updates the user_email field on all licenses associated with the given lms_user_id.

    Arguments:
        lms_user_id (str): The lms_user_id associated with licenses that should be updated
        new_email (str): The email that will overwrite curent user_email fields

    """

    user_licenses = License.objects.filter(
        lms_user_id=lms_user_id,
    )
    for lcs in user_licenses:
        lcs.user_email = new_email

    License.bulk_update(user_licenses, ['user_email'])
