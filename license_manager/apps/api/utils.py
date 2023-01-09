""" Utility functions. """
import logging
import os
import urllib
import uuid

import boto3
from django.http import Http404
from django.shortcuts import get_object_or_404
from edx_rbac.utils import get_decoded_jwt
from rest_framework.exceptions import ParseError, status

from license_manager.apps.subscriptions import constants
from license_manager.apps.subscriptions.exceptions import (
    LicenseNotFoundError,
    LicenseRevocationError,
)
from license_manager.apps.subscriptions.models import CustomerAgreement, License
from license_manager.apps.subscriptions.utils import (
    get_license_activation_link,
    localized_utcnow,
)


logger = logging.getLogger(__name__)


def get_requested_enterprise_uuid(request):
    """
    Returns the enterprise uuid as a uuid.UUID object
    based on the ``enterprise_customer_uuid`` query parameter in the given request,
    or None if that paramter is not present.
    """
    enterprise_customer_uuid = request.query_params.get('enterprise_customer_uuid')
    if not enterprise_customer_uuid:
        return None
    try:
        return uuid.UUID(enterprise_customer_uuid)
    except ValueError as exc:
        raise ParseError(f'{enterprise_customer_uuid} is not a valid uuid.') from exc


def get_customer_agreement_from_request_enterprise_uuid(request):
    """
    Helper function to return the CustomerAgreement, if any, associated with the specified ``enterprise_customer_uuid``.
    """
    enterprise_customer_uuid = request.query_params.get('enterprise_customer_uuid')
    return get_object_or_404(
        CustomerAgreement,
        enterprise_customer_uuid=enterprise_customer_uuid,
    )


def get_context_for_customer_agreement_from_request(request):
    """
    Helper function to return the permission context (i.e., EnterpriseCustomer uuid) for the
    CustomerAgreement associated with the specified ``enterprise_customer_uuid`` query param.
    """
    customer_agreement = get_customer_agreement_from_request_enterprise_uuid(request)
    return customer_agreement.enterprise_customer_uuid


def get_activation_key_from_request(request):
    """
    Helper function to get an ``activation_key``, in the form of a UUID4, from a
    request's query params.

    Params:
        ``request`` - A DRF Request object.

    Returns: An activation_key UUID.
    """
    try:
        return uuid.UUID(request.query_params['activation_key'])
    except KeyError as exc:
        raise ParseError('activation_key is a required parameter') from exc
    except ValueError as exc:
        raise ParseError('{} is not a valid activation key.'.format(request.query_params['activation_key'])) from exc


def get_key_from_jwt(decoded_jwt, key):
    """
    Helper to get the provided ``key`` out of a decoded JWT or raise a validation error if not found in the JWT.
    """
    value = decoded_jwt.get(key)
    if not value:
        raise ParseError(f'`{key}` is required and could not be found in your jwt')

    return value


def get_email_from_request(request):
    """
    Helper to get the ``email`` value provided in a request's JWT.
    """
    decoded_jwt = get_decoded_jwt(request)
    return get_key_from_jwt(decoded_jwt, 'email')


def get_context_from_subscription_plan_by_activation_key(request):
    """
    Helper function to return the permission context (i.e., enterprise customer uuid) from active
    subscription plan associated with the license identified by the ``activation_key`` query param
    on a request and the ``email`` provided in the request's JWT.

    Params:
        ``request`` - A DRF Request object.

    Returns: The ``enterprise_customer_uuid`` associated with the user's license.
    """
    today = localized_utcnow()
    activation_key = get_activation_key_from_request(request)

    try:
        user_license = License.objects.get(
            activation_key=activation_key,
            user_email=get_email_from_request(request),
            subscription_plan__is_active=True,
            subscription_plan__start_date__lte=today,
            subscription_plan__expiration_date__gte=today,
        )
    except License.DoesNotExist as exc:
        decoded_jwt = get_decoded_jwt(request)
        lms_user_id = get_key_from_jwt(decoded_jwt, 'user_id')
        logger.exception(
            'License not found for activation key %s for user %s',
            activation_key,
            lms_user_id
        )
        raise Http404('No License matches the given query.') from exc

    return user_license.subscription_plan.customer_agreement.enterprise_customer_uuid


def check_missing_licenses(customer_agreement, user_emails, course_run_keys, subscription_uuid=None):
    """
    Helper function to check that each of the provided learners has a valid subscriptions license for the provided
    courses.

    Uses a map to track:
        <plan_key>: <plan_contains_course>
    where, plan_key = {subscription_plan.uuid}_{course_key}
    This will help us memoize the value of the subscription_plan.contains_content([course_key])
    to avoid repeated requests to the enterprise catalog endpoint for the same information
    """
    missing_subscriptions = {}
    licensed_enrollment_info = []

    subscription_plan_course_map = {}

    enterprise_slug = customer_agreement.enterprise_customer_slug

    subscription_plan_filter = [subscription_uuid] if subscription_uuid else customer_agreement.subscriptions.all()

    logger.info('[check_missing_licenses] Starting to iterate over all `user_emails`...')

    for email in set(user_emails):
        logger.info(f'[check_missing_licenses] handling user email {email}')
        filtered_licenses = License.objects.filter(
            subscription_plan__in=subscription_plan_filter,
            user_email=email,
        )

        logger.info('[check_missing_licenses] user licenses for email %s: %s', email, filtered_licenses)

        # order licenses by their associated subscription plan expiration date
        ordered_licenses_by_expiration = sorted(
            filtered_licenses,
            key=lambda user_license: user_license.subscription_plan.expiration_date,
            reverse=True,
        )

        for course_key in set(course_run_keys):
            plan_found = False
            for user_license in ordered_licenses_by_expiration:
                logger.info('[check_missing_licenses] handling user license %s', str(user_license.uuid))
                subscription_plan = user_license.subscription_plan
                plan_key = f'{subscription_plan.uuid}_{course_key}'
                if plan_key in subscription_plan_course_map:
                    plan_contains_content = subscription_plan_course_map.get(plan_key)
                else:
                    plan_contains_content = subscription_plan.contains_content([course_key])
                    subscription_plan_course_map[plan_key] = plan_contains_content
                logger.info(
                    '[check_missing_licenses] does plan (%s) contain content?: %s',
                    str(subscription_plan.uuid),
                    plan_contains_content,
                )
                if plan_contains_content:
                    this_enrollment = {
                        'email': email,
                        'course_run_key': course_key,
                        'license_uuid': str(user_license.uuid)
                    }
                    # assigned, not yet activated, incliude activation URL
                    if user_license.status == constants.ASSIGNED:
                        this_enrollment['activation_link'] = get_license_activation_link(
                            enterprise_slug,
                            user_license.activation_key,
                        )
                    licensed_enrollment_info.append(this_enrollment)
                    plan_found = True
            if not plan_found:
                logger.info('[check_missing_licenses] subscription plan not found plan')
                if missing_subscriptions.get(email):
                    missing_subscriptions[email].append(course_key)
                else:
                    missing_subscriptions[email] = [course_key]

    return missing_subscriptions, licensed_enrollment_info


STATUS_CODES_BY_EXCEPTION = {
    LicenseNotFoundError: status.HTTP_404_NOT_FOUND,
    LicenseRevocationError: status.HTTP_400_BAD_REQUEST,
}


def get_http_status_for_exception(exc):
    return STATUS_CODES_BY_EXCEPTION.get(
        exc.__class__,
        status.HTTP_500_INTERNAL_SERVER_ERROR,
    )


def get_custom_text(data):
    """
    Returns a dictionary with the custom text given in the POST data.
    """
    return {
        'greeting': data.get('greeting', ''),
        'closing': data.get('closing', ''),
    }


def _get_short_file_name(long_file_name):
    return long_file_name.split("/")[-1]


def upload_file_to_s3(file_name, bucket, object_name=None):
    """Upload a file to an S3 bucket

    :param file_name: File to upload
    :param bucket: Bucket to upload to
    :param object_name: S3 object name. If not specified then file_name is used
    :return: URL of object uploaded or raises botocore.exceptions.ClientError
    """

    # If S3 object_name was not specified, use file_name
    if object_name is None:
        object_name = os.path.basename(file_name)

    # Upload the file
    s3_client = boto3.client('s3')
    s3_client.upload_file(file_name, bucket, object_name)

    # https://stackoverflow.com/a/56090535
    # https://aws.amazon.com/fr/blogs/aws/amazon-s3-path-deprecation-plan-the-rest-of-the-story/
    return f'''https://{bucket}.s3.amazonaws.com/{urllib.parse.quote(object_name, safe="~()*!.'")}'''


def create_presigned_url(bucket_name, object_name, expiration=300):
    """Generate a presigned URL to share an S3 object

    :param bucket_name: string
    :param object_name: string
    :param expiration: Time in seconds for the presigned URL to remain valid
    :return: Presigned URL as string or raises botocore.exceptions.ClientError
    """

    # Generate a presigned URL for the S3 object
    s3_client = boto3.client('s3')

    response = s3_client.generate_presigned_url(
        'get_object',
        Params={
            'Bucket': bucket_name,
            'Key': object_name,
            "ResponseContentDisposition": f'attachment; filename={_get_short_file_name(object_name)}',
        },
        ExpiresIn=expiration
    )

    # The response contains the presigned URL
    return response
