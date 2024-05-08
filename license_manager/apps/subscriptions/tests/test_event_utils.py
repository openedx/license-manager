"""
Tests for the event_utils.py module.
"""
from unittest import mock

from pytest import mark

from license_manager.apps.subscriptions.constants import (
    ASSIGNED,
    ENTERPRISE_BRAZE_ALIAS_LABEL,
    SegmentEvents,
)
from license_manager.apps.subscriptions.event_utils import (
    _iso_8601_format_string,
    _track_batch_events_via_braze_alias,
    get_license_tracking_properties,
    track_license_changes,
)
from license_manager.apps.subscriptions.tests.factories import (
    LicenseFactory,
    SubscriptionPlanFactory,
)
from license_manager.apps.subscriptions.utils import localized_utcnow


@mark.django_db
def test_get_license_tracking_properties():
    test_email = 'edx@myexample.com'
    assigned_license = LicenseFactory.create(
        subscription_plan=SubscriptionPlanFactory.create(),
        lms_user_id=5,
        user_email=test_email,
        status=ASSIGNED,
        auto_applied=True)
    flat_data = get_license_tracking_properties(assigned_license)
    assert flat_data['license_uuid'] == str(assigned_license.uuid)
    assert flat_data['license_activation_key'] == str(assigned_license.activation_key)
    assert flat_data['previous_license_uuid'] == ''
    assert flat_data['assigned_date'] == _iso_8601_format_string(assigned_license.assigned_date)
    assert flat_data['activation_date'] == _iso_8601_format_string(assigned_license.activation_date)
    assert flat_data['assigned_lms_user_id'] == assigned_license.lms_user_id
    assert flat_data['assigned_email'] == test_email
    assert flat_data['auto_applied'] is True
    assert flat_data['enterprise_customer_uuid'] \
        == str(assigned_license.subscription_plan.customer_agreement.enterprise_customer_uuid)
    assert flat_data['enterprise_customer_slug'] \
        == assigned_license.subscription_plan.customer_agreement.enterprise_customer_slug
    assert flat_data['expiration_processed'] \
        == assigned_license.subscription_plan.expiration_processed
    assert flat_data['customer_agreement_uuid'] \
        == str(assigned_license.subscription_plan.customer_agreement.uuid)
    assert flat_data['enterprise_customer_name'] \
        == assigned_license.subscription_plan.customer_agreement.enterprise_customer_name

    # Check that all the data is a basic type that can be serialized so it will be clean in segment:
    for k, v in flat_data.items():
        assert isinstance(k, str)
        assert isinstance(v, (str, int, bool))


@mark.django_db
@mock.patch('license_manager.apps.subscriptions.event_utils.get_license_tracking_properties', return_value={})
@mock.patch('license_manager.apps.subscriptions.event_utils.track_event')
def test_track_license_changes(mock_track_event, _):
    licenses = LicenseFactory.create_batch(5)
    track_license_changes(licenses, SegmentEvents.LICENSE_CREATED)
    assert mock_track_event.call_count == 5
    mock_track_event.assert_called_with(None, SegmentEvents.LICENSE_CREATED, {})


@mark.django_db
@mock.patch(
    'license_manager.apps.subscriptions.event_utils.get_license_tracking_properties', return_value={'counter': 1},
)
@mock.patch('license_manager.apps.subscriptions.event_utils.track_event')
def test_track_license_changes_with_properties(mock_track_event, _):
    licenses = LicenseFactory.create_batch(5)
    track_license_changes(licenses, SegmentEvents.LICENSE_CREATED, {'counter': 2})
    assert mock_track_event.call_count == 5
    mock_track_event.assert_called_with(None, SegmentEvents.LICENSE_CREATED, {'counter': 2})


@mark.django_db
@mock.patch('license_manager.apps.subscriptions.event_utils.BrazeApiClient', return_value=mock.MagicMock())
def test_track_event_via_braze_alias(mock_braze_client):
    test_email = 'edx@myexample.com'
    assigned_license = LicenseFactory.create(
        subscription_plan=SubscriptionPlanFactory.create(),
        lms_user_id=5,
        user_email=test_email,
        status=ASSIGNED,
        auto_applied=True)
    test_event_name = 'test-event-name'
    test_event_properties = {
        'license_uuid': str(assigned_license.uuid),
        'enterprise_customer_slug': assigned_license.subscription_plan.customer_agreement.enterprise_customer_slug,
    }
    expected_user_alias = {
        "alias_name": test_email,
        "alias_label": ENTERPRISE_BRAZE_ALIAS_LABEL,
    }
    expected_attributes = {
        "user_alias": expected_user_alias,
        "email": test_email,
        "is_enterprise_learner": True,
        "_update_existing_only": False,
        "license_uuid": str(assigned_license.uuid),
        "enterprise_customer_slug": assigned_license.subscription_plan.customer_agreement.enterprise_customer_slug,
    }
    expected_event = {
        "user_alias": expected_user_alias,
        "name": test_event_name,
        "time": _iso_8601_format_string(localized_utcnow()),
        "properties": test_event_properties,
        "_update_existing_only": False,
    }
    _track_batch_events_via_braze_alias(test_event_name, {test_email: test_event_properties})
    mock_braze_client.return_value.create_braze_alias.assert_any_call([test_email], ENTERPRISE_BRAZE_ALIAS_LABEL)
    mock_braze_client.return_value.track_user.assert_any_call(attributes=[expected_attributes], events=[expected_event])
