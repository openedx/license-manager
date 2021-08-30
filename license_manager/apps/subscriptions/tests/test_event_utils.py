"""
Tests for the event_utils.py module.
"""
from pytest import mark

from license_manager.apps.subscriptions.constants import ASSIGNED
from license_manager.apps.subscriptions.event_utils import (
    _iso_8601_format_string,
    get_license_tracking_properties,
)
from license_manager.apps.subscriptions.tests.factories import (
    LicenseFactory,
    SubscriptionPlanFactory,
)


@mark.django_db
def test_get_license_tracking_properties():
    test_email = 'edx@myexample.com'
    assigned_license = LicenseFactory.create(
        subscription_plan=SubscriptionPlanFactory.create(),
        lms_user_id=5,
        user_email=test_email,
        status=ASSIGNED)
    flat_data = get_license_tracking_properties(assigned_license)
    assert flat_data['license_uuid'] == str(assigned_license.uuid)
    assert flat_data['previous_license_uuid'] == ''
    assert flat_data['assigned_date'] == _iso_8601_format_string(assigned_license.assigned_date)
    assert flat_data['activation_date'] == _iso_8601_format_string(assigned_license.activation_date)
    assert flat_data['assigned_lms_user_id'] == assigned_license.lms_user_id
    assert flat_data['assigned_email'] == test_email
    assert flat_data['enterprise_customer_uuid'] \
        == str(assigned_license.subscription_plan.customer_agreement.enterprise_customer_uuid)
    assert flat_data['enterprise_customer_slug'] \
        == assigned_license.subscription_plan.customer_agreement.enterprise_customer_slug
    assert flat_data['expiration_processed'] \
        == assigned_license.subscription_plan.expiration_processed
    assert flat_data['customer_agreement_uuid'] \
        == str(assigned_license.subscription_plan.customer_agreement.uuid)

    # Check that all the data is a basic type that can be serialized so it will be clean in segment:
    for k, v in flat_data.items():
        assert isinstance(k, str)
        assert (isinstance(v, str) or isinstance(v, int) or isinstance(v, bool))
