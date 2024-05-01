""" Utility functions for the subscriptions app. """
import hashlib
import hmac
import re
from base64 import b64encode
from datetime import datetime

from django.conf import settings
from pytz import UTC

from license_manager.apps.subscriptions.constants import (
    DEFAULT_EMAIL_SENDER_ALIAS,
    MAX_NUM_LICENSES
)
from requests.exceptions import HTTPError
from rest_framework import status

from license_manager.apps.api_client.enterprise_catalog import (
    EnterpriseCatalogApiClient,
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


def validate_enterprise_catalog_uuid(self):
        """
        Verifies that the enterprise customer has a catalog with the given enterprise_catalog_uuid.
        """

        try:
            catalog = EnterpriseCatalogApiClient().get_enterprise_catalog(self.instance.enterprise_catalog_uuid)
            catalog_enterprise_customer_uuid = catalog['enterprise_customer']
            if str(self.instance.enterprise_customer_uuid) != catalog_enterprise_customer_uuid:
                self.add_error(
                    'enterprise_catalog_uuid',
                    'A catalog with the given UUID does not exist for this enterprise customer.',
                )
                return False
            return True
        except HTTPError as ex:
            if ex.response.status_code == status.HTTP_404_NOT_FOUND:
                self.add_error(
                    'enterprise_catalog_uuid',
                    'A catalog with the given UUID does not exist for this enterprise customer.',
                )
            else:
                self.add_error(
                    'enterprise_catalog_uuid',
                    f'Could not verify the given UUID: {ex}. Please try again.',
                )
            return False
        

def validate_subscription_plan_payload(payload, handle_error, log_validation_error=None, is_admin_form=True):
    # Ensure that we are getting an enterprise catalog uuid from the field itself or the linked customer agreement
    # when the subscription is first created.
    if 'customer_agreement' in payload:
        form_customer_agreement = payload.get('customer_agreement')
        form_enterprise_catalog_uuid = payload.get('enterprise_catalog_uuid')
        if not form_customer_agreement.default_enterprise_catalog_uuid and not form_enterprise_catalog_uuid:
            if log_validation_error:
                log_validation_error('bad catalog uuid')
            handle_error(
                'enterprise_catalog_uuid',
                'The subscription must have an enterprise catalog uuid from itself or its customer agreement',
            )
            return False

    form_num_licenses = payload.get('num_licenses', 0)
    # Only internal use subscription plans to have more than the maximum number of licenses
    if form_num_licenses > MAX_NUM_LICENSES and not payload.get('for_internal_use_only'):
        if log_validation_error:
            log_validation_error('exceeded max licenses')
        handle_error(
            'num_licenses',
            f'Non-test subscriptions may not have more than {MAX_NUM_LICENSES} licenses',
        )
        return False

    # Ensure the revoke max percentage is between 0 and 100
    if payload.get('is_revocation_cap_enabled') and payload.get('revoke_max_percentage') > 100:
        if log_validation_error:
            log_validation_error('bad max revoke settings')
        handle_error('revoke_max_percentage',
                     'Must be a valid percentage (0-100).')
        return False

    product = payload.get('product')
    # must check for product vaildations if request initiated from admin form.
    # in case of views, serializers will handle the validation
    if (product or is_admin_form):
        if not product:
            if log_validation_error:
                log_validation_error('no product specified')
            handle_error(
                'product',
                'You must specify a product.',
            )
            return False

        if (
                product.plan_type.sf_id_required
                and payload.get('salesforce_opportunity_line_item') is None
                or not verify_sf_opportunity_product_line_item(payload.get(
                'salesforce_opportunity_line_item'))
        ):
            if log_validation_error:
                log_validation_error('no SF ID')
            handle_error(
                'salesforce_opportunity_line_item',
                'You must specify Salesforce ID for selected product. It must start with \'00k\'.',
            )
            return False

    if settings.VALIDATE_FORM_EXTERNAL_FIELDS and payload.get('enterprise_catalog_uuid') and \
            not validate_enterprise_catalog_uuid():
        if log_validation_error:
            log_validation_error('bad catalog uuid validation')
        return False

    return True
