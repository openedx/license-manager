"""
Utility methods for sending events to Braze or Segment.
"""
import logging
import uuid

import analytics
import requests
from braze.exceptions import BrazeClientError
from django.conf import settings
from django.db.models import prefetch_related_objects

from license_manager.apps.api_client.braze import BrazeApiClient
from license_manager.apps.subscriptions.constants import (
    ENTERPRISE_BRAZE_ALIAS_LABEL,
)
from license_manager.apps.subscriptions.utils import localized_utcnow


logger = logging.getLogger(__name__)


def _iso_8601_format_string(datetime):
    """
    Helper to return an ISO8601-formatted datetime string, with a trailing 'Z'.
    Returns an empty string if date is None.
    """
    if datetime is None:
        return ''
    return datetime.strftime('%Y-%m-%dT%H:%M:%SZ')


def _get_braze_alias(email):
    return {
        "alias_name": email,
        "alias_label": ENTERPRISE_BRAZE_ALIAS_LABEL,
    }


def _get_braze_event(braze_alias, event_name, properties):
    return {
        "user_alias": braze_alias,
        "name": event_name,
        "time": _iso_8601_format_string(localized_utcnow()),
        "properties": properties,
        "_update_existing_only": False,
    }


def _get_braze_attributes(email, braze_alias):
    # we want an email & is_enterprise_learner attribute
    # we want _update_existing_only=False so we create a new profile if needed
    return {
        "user_alias": braze_alias,
        "email": email,
        "is_enterprise_learner": True,
        "_update_existing_only": False,
    }


def _profile_attributes_from_properties(properties):
    """
    Gather event properties that should eventually be copied
    into the braze user profile (associated with an alias).
    """
    event_properites_to_copy_to_profile = [
        'enterprise_customer_uuid',
        'enterprise_customer_slug',
        'enterprise_customer_name',
        'license_uuid',
        'license_activation_key',
    ]

    profile_attributes = {}

    for event_property in event_properites_to_copy_to_profile:
        event_value = properties.get(event_property)
        if event_value is not None:
            profile_attributes[event_property] = event_value

    return profile_attributes


def _track_batch_events_via_braze_alias(event_name, properties_by_email):
    """
    Allows batch tracking of users without an lms user id.
    """
    braze_alias_emails = []
    braze_attributes = []
    braze_events = []

    # synthetic batch id to help us correlate log messages
    batch_id = uuid.uuid4()

    for email, properties in properties_by_email.items():
        # Create an alias and stash the email in a list we'll send as a batch to braze via `create_braze_alias()`
        braze_alias_emails.append(email)
        user_alias = _get_braze_alias(email)

        # Create an attribute record and stash in a list we'll send to braze via `track_user()`.
        attribute_record = _get_braze_attributes(email, user_alias)
        attribute_record.update(_profile_attributes_from_properties(properties))
        braze_attributes.append(attribute_record)

        # Create an event record and stash in a list we'll send to braze via `track_user()`.
        event_record = _get_braze_event(user_alias, event_name, properties)
        braze_events.append(event_record)

        msg = 'Added braze alias/attribute/event to batch %s for pending learner with license %s, enterprise %s.'
        logger.info(msg, batch_id, properties['license_uuid'], properties['enterprise_customer_slug'])

    # Now send the data to braze
    braze_client_instance = BrazeApiClient()
    try:
        braze_client_instance.create_braze_alias(braze_alias_emails, ENTERPRISE_BRAZE_ALIAS_LABEL)
        logger.info('Sent batch of braze aliases with batch id %s', batch_id)
    except BrazeClientError as exc:
        logger.exception('Failed to create braze alias')
        raise exc

    try:
        braze_client_instance.track_user(
            attributes=braze_attributes,
            events=braze_events,
        )
        logger.info('Sent batch of braze attribute/events to track_user endpoint with batch id %s', batch_id)
    except BrazeClientError as exc:
        logger.exception('Failed to track user via braze')
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
                assigned_email = properties['assigned_email']
                if assigned_email:
                    _track_batch_events_via_braze_alias(event_name, {assigned_email: properties})
            else:
                analytics.track(user_id=lms_user_id, event=event_name, properties=properties)
        except Exception as exc:  # pylint: disable=broad-except
            logger.exception(exc)
    else:
        logger.warning(
            "Event {} for user_id {} not tracked because SEGMENT_KEY not set".format(event_name, lms_user_id)
        )


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


def track_license_changes(licenses, event_name, properties=None, is_batch_assignment=False):
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

    if ``is_batch_assignment``, call `track_users` in braze with a list of users to alias and track, skip
    over the normal `track_event()` call.
    """
    properties = properties or {}
    # prefetch related objects used in get_license_tracking_properties
    prefetch_related_objects(licenses, '_renewed_from', 'subscription_plan', 'subscription_plan__customer_agreement')

    if is_batch_assignment:
        properties_by_email = {
            lcs.user_email: {**get_license_tracking_properties(lcs), **properties}
            for lcs in licenses
        }
        _track_batch_events_via_braze_alias(event_name, properties_by_email)
    else:
        for lcs in licenses:
            event_properties = {**get_license_tracking_properties(lcs), **properties}
            track_event(lcs.lms_user_id, event_name, event_properties)


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
