import logging

import analytics
from django.conf import settings


logger = logging.getLogger(__name__)


def _iso_8601_format_string(datetime):
    """
    Helper to return an ISO8601-formatted datetime string, with a trailing 'Z'.
    Returns an empty string if date is None.
    """
    if datetime is None:
        return ''
    return datetime.strftime('%Y-%m-%dT%H:%M:%SZ')


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

    if hasattr(settings, "SEGMENT_KEY") and settings.SEGMENT_KEY:
        try:  # We should never raise an exception when not able to send a tracking event
            analytics.track(user_id, event_name, properties)
        except Exception:  # pylint: disable=broad-except
            logger.exception()
    else:
        logger.warning("Event {} for user_id {} not tracked because SEGMENT_KEY not set". format(event_name, user_id))


def get_license_tracking_properties(license_obj):
    """ Uses a License object to build necessary license-related properties to send with a license event.
        See See docs/segment_events.rst.

    Args:
        license: License object to use for data population.

    """
    assigned_date_formatted = ''
    if license_obj.assigned_date:
        assigned_date_formatted = _iso_8601_format_string(license_obj.assigned_date)

    activation_date_formatted = ''
    if license_obj.activation_date:
        activation_date_formatted = _iso_8601_format_string(license_obj.activation_date)

    renewed_from_formatted = ''
    if license_obj.renewed_from:
        renewed_from_formatted = str(license_obj.renewed_from.uuid)
    license_data = {
        "license_uuid": str(license_obj.uuid),
        "previous_license_uuid": renewed_from_formatted,
        "assigned_date": assigned_date_formatted,
        "activation_date": activation_date_formatted,
        "assigned_lms_user_id": (license_obj.lms_user_id or ''),
        "assigned_email": (license_obj.user_email or ''),
        "expiration_processed": license_obj.subscription_plan.expiration_processed
    }

    user_who_made_change = license_obj.history.latest().history_user
    license_data.update({
        'user_id': (user_who_made_change or '')
    })

    if license_obj and license_obj.subscription_plan and license_obj.subscription_plan.customer_agreement:
        license_data.update(get_enterprise_tracking_properties(
            license_obj.subscription_plan.customer_agreement))
    else:
        logger.warning("Tried to set up Segment tracking data for license {},"
                       "but missing subscription plan or customer agreement."
                       .format(license_obj.uuid))

    return license_data


def get_enterprise_tracking_properties(customer_agreement):
    """
    Get the UUIDs from the database about the enterprise CustomerAgreement

    Args:
        customer_agreement: CustomerAgreement object to use for data population.

    Returns:
        a (dict) containing the UUIDs in the customer_agreement model.
    """
    return {
        'enterprise_customer_uuid': str(customer_agreement.enterprise_customer_uuid),
        'customer_agreement_uuid': str(customer_agreement.uuid),
        'enterprise_customer_slug': customer_agreement.enterprise_customer_slug,
    }
