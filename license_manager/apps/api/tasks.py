import logging
from smtplib import SMTPException

from celery import shared_task
from celery_utils.logged_task import LoggedTask
from django.db import transaction

import license_manager.apps.subscriptions.api as subscriptions_api
from license_manager.apps.api import utils
from license_manager.apps.api_client.enterprise import EnterpriseApiClient
from license_manager.apps.subscriptions.constants import (
    PENDING_ACCOUNT_CREATION_BATCH_SIZE,
    REVOCABLE_LICENSE_STATUSES,
)
from license_manager.apps.subscriptions.emails import (
    send_activation_emails,
    send_onboarding_email,
    send_revocation_cap_notification_email,
)
from license_manager.apps.subscriptions.models import (
    CustomerAgreement,
    License,
    SubscriptionPlan,
)
from license_manager.apps.subscriptions.utils import (
    chunks,
    get_enterprise_reply_to_email,
    get_enterprise_sender_alias,
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


@shared_task(base=LoggedTask)
def enterprise_enrollment_license_subsidy_task(job_id, enterprise_customer_uuid, learner_emails, course_run_keys, notify_learners, subscription_uuid=None):
    """
    Enroll a list of enterprise learners into a list of course runs with or without notifying them. Optionally, filter license check by a specific subscription.

    Arguments:
        job_id (str): UUID (string representation) created by the enqueuing process for logging and (future) progress tracking table updates.
        enterprise_customer_uuid (str): UUID (string representation) the enterprise customer id
        learner_emails (list(str)): email addresses of the learners to enroll
        course_run_keys (list(str)): course keys of the courses to enroll the learners into
        notify_learners (bool): whether or not to send notifications of their enrollment to the learners
        subscription_uuid (str): UUID (string representation) of the specific enterprise subscription to use when validating learner licenses
    """
    results = {}
    results['successes'] = dict()
    results['failures'] = dict()
    results['pending'] = dict()
    # these keys are from the orginal endpoint, retaining them for now
    results['bulk_enrollment_errors'] = list()
    results['failed_license_checks'] = list()
    results['failed_enrollments'] = list()

    logger.info("starting job_id={} enterprise_enrollment_license_subsidy_task for enterprise_customer_uuid={}".format(job_id, enterprise_customer_uuid))

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
                    results['failures'][failed_email] = missing_subscriptions.get(failed_email)
                msg = 'One or more of the learners entered do not have a valid subscription for your requested courses. ' \
                      'Learners: {}'.format(missing_subscriptions)
                results['failed_license_checks'].append(missing_subscriptions)
                logger.error(msg)

            if licensed_enrollment_info:
                options = {
                    'licenses_info': licensed_enrollment_info,
                    'notify': notify_learners
                }
                enrollment_response = EnterpriseApiClient().bulk_enroll_enterprise_learners(
                    str(enterprise_customer_uuid), options
                )

                enrollment_result = enrollment_response.json()
                for result_key in ['successes', 'pending', 'failures']:
                    for result_dict in enrollment_result.get(result_key):
                        result_email = result_dict.get('email')
                        result_course_key = result_dict.get('course_run_key')
                        if results[result_key].get(result_email):
                            results[result_key][result_email].append(result_course_key)
                        else:
                            results[result_key][result_email] = [result_course_key]

                if enrollment_result.get('invalid_email_addresses'):
                    for result_email in enrollment_result['invalid_email_addresses']:
                        if results['failures'].get(result_email):
                            results['failures'][result_email] = results['failures'][result_email] + course_run_key_batch
                        else:
                            results['failures'][result_email] = course_run_key_batch

                # Check for bulk enrollment errors
                if enrollment_response.status_code >= 400 and enrollment_response.status_code != 409:
                    try:
                        response_json = enrollment_response.json()
                    except JSONDecodeError:
                        # Catch uncaught exceptions from enterprise
                        results['bulk_enrollment_errors'].append(enrollment_response.reason)
                    else:
                        msg = 'Encountered a validation error when requesting bulk enrollment. Endpoint returned with ' \
                              'error: {}'.format(response_json)
                        logger.error(msg)

                        # check for non field specific errors
                        if response_json.get('non_field_errors'):
                            results['bulk_enrollment_errors'].append(response_json['non_field_errors'])

                        # check for param field specific validation errors
                        for param in options:
                            if response_json.get(param):
                                results['bulk_enrollment_errors'].append(response_json.get(param))

                else:
                    if enrollment_result.get('failures'):
                        results['failed_enrollments'].append(enrollment_result['failures'])

    return results
