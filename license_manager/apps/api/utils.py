""" Utility functions. """
import uuid
import os

from django.shortcuts import get_object_or_404
from edx_rbac.utils import get_decoded_jwt
from rest_framework.exceptions import ParseError

import boto3

from license_manager.apps.subscriptions import constants
from license_manager.apps.subscriptions.models import (
    CustomerAgreement,
    License,
)
from license_manager.apps.subscriptions.utils import (
    get_license_activation_link,
    localized_utcnow,
)


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
    user_license = get_object_or_404(
        License,
        activation_key=get_activation_key_from_request(request),
        user_email=get_email_from_request(request),
        subscription_plan__is_active=True,
        subscription_plan__start_date__lte=today,
        subscription_plan__expiration_date__gte=today,
    )
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
    for email in set(user_emails):
        filtered_licenses = License.objects.filter(
            subscription_plan__in=subscription_plan_filter,
            user_email=email,
        )

        # order licenses by their associated subscription plan expiration date
        ordered_licenses_by_expiration = sorted(
            filtered_licenses,
            key=lambda user_license: user_license.subscription_plan.expiration_date,
            reverse=True,
        )
        for course_key in set(course_run_keys):
            plan_found = False
            for user_license in ordered_licenses_by_expiration:
                subscription_plan = user_license.subscription_plan
                plan_key = f'{subscription_plan.uuid}_{course_key}'
                if plan_key in subscription_plan_course_map:
                    plan_contains_content = subscription_plan_course_map.get(plan_key)
                else:
                    plan_contains_content = subscription_plan.contains_content([course_key])
                    subscription_plan_course_map[plan_key] = plan_contains_content

                if plan_contains_content:
                    this_enrollment = {
                        'email': email,
                        'course_run_key': course_key,
                        'license_uuid': str(user_license.uuid)
                    }
                    # assigned, not yet activated, incliude activation URL
                    if user_license.status == constants.ASSIGNED:
                        this_enrollment['activation_link'] = get_license_activation_link(enterprise_slug, user_license.activation_key)
                    licensed_enrollment_info.append(this_enrollment)
                    plan_found = True
            if not plan_found:
                if missing_subscriptions.get(email):
                    missing_subscriptions[email].append(course_key)
                else:
                    missing_subscriptions[email] = [course_key]

    return missing_subscriptions, licensed_enrollment_info


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


def create_presigned_url(bucket_name, object_name, expiration=3600):
    """Generate a presigned URL to share an S3 object

    :param bucket_name: string
    :param object_name: string
    :param expiration: Time in seconds for the presigned URL to remain valid
    :return: Presigned URL as string or raises botocore.exceptions.ClientError
    """

    # Generate a presigned URL for the S3 object
    s3_client = boto3.client('s3')

    response = s3_client.generate_presigned_url('get_object',
                                                Params={'Bucket': bucket_name,
                                                        'Key': object_name},
                                                ExpiresIn=expiration)

    # The response contains the presigned URL
    return response

