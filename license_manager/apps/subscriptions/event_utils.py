import logging

import analytics
from django.conf import settings

from license_manager.apps.subscriptions.models import CustomerAgreement


logger = logging.getLogger(__name__)


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
        try:  # We should never raise an exception when not able to send a tracking event
            analytics.track(user_id, event_name, properties)
        except Exception:  # pylint: disable=broad-except
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
        }
    except CustomerAgreement.DoesNotExist:
        logger.warning("Unable to find a CustomerAgreement for UUID: {}".format(enterprise_customer_uuid))
    except Exception:  # pylint: disable=broad-except
        logger.exception()

    return {}
