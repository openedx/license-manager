"""
Utility methods for sending events to Braze or Segment.
"""
import logging

import analytics
import requests
from braze.exceptions import BrazeClientError
from django.conf import settings
from django.db.models import prefetch_related_objects
from openedx_events.enterprise.data import SubscriptionLicenseData
from openedx_events.enterprise.signals import SUBSCRIPTION_LICENSE_MODIFIED

from license_manager.apps.api_client.braze import BrazeApiClient
from license_manager.apps.subscriptions.constants import (
    ENTERPRISE_BRAZE_ALIAS_LABEL,
)
from license_manager.apps.subscriptions.utils import localized_utcnow

from .apps import KAFKA_ENABLED


logger = logging.getLogger(__name__)


def _iso_8601_format_string(datetime):
    """
    Helper to return an ISO8601-formatted datetime string, with a trailing 'Z'.
    Returns an empty string if date is None.
    """
    if datetime is None:
        return ''
    return datetime.strftime('%Y-%m-%dT%H:%M:%SZ')


def _track_event_via_braze_alias(email, event_name, properties):
    """ Private helper to allow tracking for a user without an LMS User Id.
        Should be called from inside the track_event module only for exception handling.
    """
    try:
        braze_client_instance = BrazeApiClient()

        # first create an alias for this email address with the ent label
        braze_client_instance.create_braze_alias(
            [email],
            ENTERPRISE_BRAZE_ALIAS_LABEL,
        )
        logger.info('Added alias for pending learner to Braze for license {}, enterprise {}.'
                    .format(properties['license_uuid'],
                            properties['enterprise_customer_slug']))

        user_alias = {
            "alias_name": email,
            "alias_label": ENTERPRISE_BRAZE_ALIAS_LABEL,
        }

        # we want an email & is_enterprise_learner attribute
        # we want _update_existing_only=False so we create a new profile if needed
        attributes = {
            "user_alias": user_alias,
            "email": email,
            "is_enterprise_learner": True,
            "_update_existing_only": False,
        }

        events = {
            "user_alias": user_alias,
            "name": event_name,
            "time": _iso_8601_format_string(localized_utcnow()),
            "properties": properties,
            "_update_existing_only": False,
        }

        # event-level properties are not always available for personalization in braze
        # we'll copy these specific event properties into the profile attributes if we see them
        event_properites_to_copy_to_profile = [
            'enterprise_customer_uuid',
            'enterprise_customer_slug',
            'enterprise_customer_name',
            'license_uuid',
            'license_activation_key',
        ]

        for event_property in event_properites_to_copy_to_profile:
            if properties.get(event_property) is not None:
                attributes[event_property] = properties.get(event_property)

        braze_client_instance.track_user(attributes=[attributes], events=[events])
        logger.info('Sent "{}" event to Braze for license {}, enterprise {}.'
                    .format(event_name,
                            properties['license_uuid'],
                            properties['enterprise_customer_slug']))

    except BrazeClientError as exc:
        logger.exception()
        raise exc


def identify_braze_alias(lms_user_id, email_address):
    """
    Send `identify` event to Braze to link aliased Braze profiles.

    Args:
        lms_user_id (str): LMS User ID of the user we want to identify.
        email_address (str): LMS User Email of the user we want to identify.
    """
    if not (hasattr(settings, "BRAZE_API_KEY") and hasattr(settings, "BRAZE_URL")
            and settings.BRAZE_API_KEY and settings.BRAZE_URL):
        logger.warning("Alias {} not identified because BRAZE_API_KEY and BRAZE_URL not set".format(email_address))
        return

    try:  # We should never raise an exception when not able to send a tracking data
        headers = {
            'Content-Type': 'application/json',
            'Authorization': 'Bearer {}'.format(settings.BRAZE_API_KEY),
            'Accept-Encoding': 'identity'
        }
        response = requests.post(
            url=f'{settings.BRAZE_URL}/users/identify',
            headers=headers,
            json={
                'aliases_to_identify': [
                    # This hubspot alias is defined in 'hubspot_leads.py' in the edx-prefectutils repo
                    {
                        'external_id': str(lms_user_id),
                        'user_alias': {
                            'alias_label': 'hubspot',
                            'alias_name': email_address,
                        },
                    },
                    # This enterprise alias is used for Pending Learners before they activate their accounts,
                    # see the license-manager repo event_utils.py file and the ecommerce Braze client files
                    {
                        'external_id': str(lms_user_id),
                        'user_alias': {
                            'alias_label': 'Enterprise',
                            'alias_name': email_address,
                        },
                    },
                ],
            },
        )
        return response
    except Exception as exc:  # pylint: disable=broad-except
        logger.exception(exc)
        return


def track_event(lms_user_id, event_name, properties):
    """
    Send a tracking event to segment

    Args:
        lms_user_id (str): LMS User ID of the user we want tracked with this event for cross-platform tracking.
                           IF None, tracking will be attempted via unregistered learner email address.
        event_name (str): Name of the event in the format of:
                          `edx.server.license-manager.license-lifecycle.<new-status>` -  see constants.SegmentEvents
        properties (dict): All the properties of an event. See docs/segment_events.rst

    Returns:
        None
    """

    if hasattr(settings, "SEGMENT_KEY") and settings.SEGMENT_KEY:
        try:  # We should never raise an exception when not able to send a tracking event
            if not lms_user_id:
                # We dont have an LMS user id for this event, so we can't track it in segment the same way.
                logger.warning(
                    "Event {} for License Manager tracked without LMS User Id: {}".format(event_name, properties)
                )
                if properties['assigned_email']:
                    _track_event_via_braze_alias(properties['assigned_email'], event_name, properties)

                return

            analytics.track(user_id=lms_user_id, event=event_name, properties=properties)
        except Exception as exc:  # pylint: disable=broad-except
            logger.exception(exc)
    else:
        logger.warning(
            "Event {} for user_id {} not tracked because SEGMENT_KEY not set".format(event_name, lms_user_id)
        )

    if KAFKA_ENABLED.is_enabled():  # pragma: no cover
        try:
            # assigned_lms_user_id expects an integer or None, but elsewhere it is defaulted to ''
            properties_copy = dict(properties.items())
            if properties_copy['assigned_lms_user_id'] == "":
                properties_copy['assigned_lms_user_id'] = None
            license_data = SubscriptionLicenseData(**properties_copy)
            SUBSCRIPTION_LICENSE_MODIFIED.send_event(license=license_data)
        except Exception:  # pylint: disable=broad-except
            logger.exception("Exception sending event to message.")


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
        "license_activation_key": str(license_obj.activation_key),
        "previous_license_uuid": renewed_from_formatted,
        "assigned_date": assigned_date_formatted,
        "activation_date": activation_date_formatted,
        "assigned_lms_user_id": (license_obj.lms_user_id or ''),
        "assigned_email": (license_obj.user_email or ''),
        "expiration_processed": license_obj.subscription_plan.expiration_processed,
        "auto_applied": (license_obj.auto_applied or False),
    }

    if license_obj and license_obj.subscription_plan and license_obj.subscription_plan.customer_agreement:
        license_data.update(get_enterprise_tracking_properties(
            license_obj.subscription_plan.customer_agreement))
    else:
        logger.warning("Tried to set up Segment tracking data for license {},"
                       "but missing subscription plan or customer agreement."
                       .format(license_obj.uuid))

    return license_data


def track_license_changes(licenses, event_name, properties=None):
    """
    Send tracking events for changes to a list of licenses, useful when bulk changes are made.
    Prefetches related objects for licenses to prevent additional queries

    Args:
        licenses (list): List of licenses
        event_name (str): Name of the event in the format of:
                          `edx.server.license-manager.license-lifecycle.<new-status>` - see constants.SegmentEvents
        properties: (dict): Additional properties to track for each event,
                            overrides fields from get_license_tracking_properties
    Returns:
        None
    """
    properties = properties or {}
    # prefetch related objects used in get_license_tracking_properties
    prefetch_related_objects(licenses, '_renewed_from', 'subscription_plan', 'subscription_plan__customer_agreement')

    for lcs in licenses:
        event_properties = {**get_license_tracking_properties(lcs), **properties}
        track_event(
            lcs.lms_user_id,  # None for unassigned licenses, track_event will handle users with unregistered emails
            event_name,
            event_properties,
        )


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
        'enterprise_customer_name': customer_agreement.enterprise_customer_name,
    }
