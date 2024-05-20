""" Utility functions for the subscriptions app. """
import hashlib
import hmac
import re
from base64 import b64encode
from datetime import datetime

from django.conf import settings
from pytz import UTC
from requests.exceptions import HTTPError
from rest_framework import status

from license_manager.apps.api_client.enterprise_catalog import (
    EnterpriseCatalogApiClient,
)
from license_manager.apps.subscriptions.constants import (
    DEFAULT_EMAIL_SENDER_ALIAS,
)
from license_manager.apps.subscriptions.exceptions import (
    InvalidSubscriptionPlanPayloadError,
)


# pylint: disable=no-value-for-parameter
def localized_utcnow():
    """Helper function to return localized utcnow()."""
    return UTC.localize(datetime.utcnow())  # pylint: disable=no-value-for-parameter


def localized_datetime_from_datetime(datetime_obj):
    """
    Helper to return a UTC-localized datetime from an existing datetime object.
    """
    return UTC.localize(datetime_obj)


def localized_datetime(*args, **kwargs):
    """
    Helper to return a UTC-localized datetime.
    """
    return UTC.localize(datetime(*args, **kwargs))


def localized_datetime_from_date(date_obj):
    """
    Converts a date object to a UTC-localized datetime with 0 hours, minutes, and seconds.
    """
    return UTC.localize(datetime.combine(date_obj, datetime.min.time()))


def days_until(end_date):
    """
    Helper to return the number of days until the end date.
    """
    diff = end_date - localized_utcnow()
    return diff.days


def hours_until(effective_date):
    """
    Helper to return the number of hours until the effective date.
    """
    duration_until_effective_date = effective_date - localized_utcnow()
    duration_until_effective_date_s = duration_until_effective_date.total_seconds()
    duration_until_effective_date_h = divmod(duration_until_effective_date_s, 3600)[0]  # Seconds in an hour = 3600
    return duration_until_effective_date_h


def chunks(a_list, chunk_size):
    """
    Helper to break a list up into chunks. Returns a generator of lists.
    """
    for i in range(0, len(a_list), chunk_size):
        yield a_list[i:i + chunk_size]


def batch_counts(total_count, batch_size=1):
    """
    Break up a total count into equal-sized batch counts.

    Arguments:
        total_count (int): The total count to batch.
        batch_size (int): The size of each batch. Defaults to 1.
    Returns:
        generator: returns the count for each batch.
    """
    num_full_batches, last_batch_count = divmod(total_count, batch_size)
    for _ in range(num_full_batches):
        yield batch_size
    if last_batch_count > 0:
        yield last_batch_count


def get_learner_portal_url(enterprise_slug):
    """
    Returns the link to the learner portal, given an enterprise slug.
    Does not contain a trailing slash.
    """
    return '{}/{}'.format(settings.ENTERPRISE_LEARNER_PORTAL_BASE_URL, enterprise_slug)


def get_admin_portal_url(enterprise_slug):
    """
    Returns the link to the admin portal, given an enterprise slug.
    Does not contain a trailing slash.
    """
    return '{}/{}'.format(settings.ENTERPRISE_ADMIN_PORTAL_BASE_URL, enterprise_slug)


def get_license_activation_link(enterprise_slug, activation_key):
    """
    Returns the activation link displayed in the activation email sent to a learner
    """
    return '/'.join((
        get_learner_portal_url(enterprise_slug),
        'licenses',
        str(activation_key),
        'activate'
    ))


def get_enterprise_sender_alias(enterprise_customer):
    """
    Returns the configured sender alias for an enterprise, if configured; otherwise
    returns the default sender alias.
    """
    return enterprise_customer.get('sender_alias') or DEFAULT_EMAIL_SENDER_ALIAS


def get_enterprise_reply_to_email(enterprise_customer):
    """
    Returns the configured reply_to email for an enterprise, if configured.
    """
    return enterprise_customer.get('reply_to') or ''


def get_subsidy_checksum(lms_user_id, course_key, license_uuid):
    """
    Hashes the (lms_user_id, course_key, license_uuid)
    and returns a base64-encoded string of the hash digest.

    Used for license subsidy verification during licensed-enrollment.
    """
    digest_function = getattr(hashlib, settings.ENTERPRISE_SUBSIDY_CHECKSUM_ALGORITHM, 'sha256')
    key = settings.ENTERPRISE_SUBSIDY_CHECKSUM_SECRET_KEY.encode()
    message = settings.ENTERPRISE_SUBSIDY_CHECKSUM_MESSAGE_FORMAT.format(
        lms_user_id=str(lms_user_id),
        course_key=str(course_key),
        license_uuid=str(license_uuid),
    ).encode()

    digest = hmac.digest(key, message, digest_function)
    return b64encode(digest).decode()


def verify_sf_opportunity_product_line_item(salesforce_opportunity_line_item):
    """
    Returns boolean value to confirm if the passed salesforce_opportunity_line_item format
    is correct
    """
    return re.search(r'^00k', salesforce_opportunity_line_item)


def validate_enterprise_catalog_uuid(enterprise_catalog_uuid, enterprise_customer_uuid):
    """
    Verifies that the enterprise customer has a catalog with the given enterprise_catalog_uuid.
    """

    try:
        catalog = EnterpriseCatalogApiClient().get_enterprise_catalog(
            enterprise_catalog_uuid)
        catalog_enterprise_customer_uuid = catalog.get('enterprise_customer', None)
        if str(enterprise_customer_uuid) != catalog_enterprise_customer_uuid:
            raise InvalidSubscriptionPlanPayloadError(
                'A catalog with the given UUID does not exist for this enterprise customer.',
            )
        return True
    except HTTPError as ex:
        if ex.response.status_code == status.HTTP_404_NOT_FOUND:
            raise InvalidSubscriptionPlanPayloadError(
                'A catalog with the given UUID does not exist for this enterprise customer.',
            ) from ex
        raise InvalidSubscriptionPlanPayloadError(
            f'Could not verify the given UUID: {ex}. Please try again.',
        ) from ex
    except Exception as ex:
        raise InvalidSubscriptionPlanPayloadError(
            f'Unknown error occured while connecting to enterprise catalog API. {ex}',
        ) from ex


def provision_licenses(subscription):
    """
    For a given subscription plan, try to provision it synchronously or asynchronously.
    Args:
        subscription: SubscriptionPlan instance
    """
    from license_manager.apps.subscriptions.tasks import (
        PROVISION_LICENSES_BATCH_SIZE,
        provision_licenses_task,
    )

    if subscription.desired_num_licenses and not subscription.last_freeze_timestamp:
        license_count_gap = subscription.desired_num_licenses - subscription.num_licenses
        if license_count_gap > 0:
            if license_count_gap <= PROVISION_LICENSES_BATCH_SIZE:
                # We can handle just one batch synchronously.
                subscription.increase_num_licenses(license_count_gap)
            else:
                # Multiple batches of licenses will need to be created, so provision them asynchronously.
                provision_licenses_task.delay(
                    subscription_plan_uuid=subscription.uuid)
