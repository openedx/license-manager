""" Utility functions for the subscriptions app. """
import analytics
from datetime import date, datetime

from django.conf import settings
from pytz import UTC

from license_manager.apps.subscriptions.constants import (
    DEFAULT_EMAIL_SENDER_ALIAS,
)
import logging

from license_manager.apps.subscriptions.models import CustomerAgreement


logger = logging.getLogger(__name__)


# pylint: disable=no-value-for-parameter
def localized_utcnow():
    """Helper function to return localized utcnow()."""
    return UTC.localize(datetime.utcnow())  # pylint: disable=no-value-for-parameter


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
    diff = end_date - date.today()
    return diff.days


def chunks(a_list, chunk_size):
    """
    Helper to break a list up into chunks. Returns a list of lists
    """
    for i in range(0, len(a_list), chunk_size):
        yield a_list[i:i + chunk_size]


def get_learner_portal_url(enterprise_slug):
    """
    Returns the link to the learner portal, given an enterprise slug.
    Does not contain a trailing slash.
    """
    return '{}/{}'.format(settings.ENTERPRISE_LEARNER_PORTAL_BASE_URL, enterprise_slug)


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

def track_event(user_id, event_name, properties):
    """
    Send a tracking event to segment

    Args:
        user_id (str): ID of the user who generated this event
        event_name (str): Name of the event in the format of: edx.server.license-manager.license-lifecycle.<new-status>
        properties (dict): All the properties of an event. See docs/segment_events.rst

    Returns:
        None
    """
    if settings.SEGMENT_KEY:
        try: # We should never raise an exception when not able to send a tracking event
            analytics.track(user_id, event_name, properties)
        except Exception: # pylint: disable=broad-except
            logger.exception()
    else:
        logger.debug("Event {} for user_id {} not tracked because SEGMENT_KEY not set". format(event_name, user_id))

def get_enterprise_tracking_properties(enterprise_customer_uuid):
    """
    Get the UUIDs from the database about the enterprise CustomerAgreement

    Args:
        enterprise_customer_uuid (str): UUID of the enterprise customer

    Returns:
        a (dict) containing the UUIDs in the customer_agreement model.
    """
    try:
        customer_agreement = CustomerAgreement.objects.get(enterprise_customer_uuid=enterprise_customer_uuid)
        return {
            'enterprise_customer_uuid': enterprise_customer_uuid,
            'customer_agreement_uuid': customer_agreement.uuid,
            'enterprise_customer_slug': customer_agreement.enterprise_customer_slug,
            'default_enterprise_catalog_uuid': customer_agreement.default_enterprise_catalog_uuid
        }
    except CustomerAgreement.DoesNotExist:
        logger.debug("Unable to find a CustomerAgreement for UUID: {}".format(enterprise_customer_uuid))
        return {}
    except Exception: # pylint: disable=broad-except
        logger.exception()
