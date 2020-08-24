"""
Testing utilities for the Subscriptions app.
"""
from datetime import date, timedelta

from faker import Factory as FakerFactory

from license_manager.apps.subscriptions.constants import ASSIGNED
from license_manager.apps.subscriptions.forms import SubscriptionPlanForm
from license_manager.apps.subscriptions.tests.factories import (
    LicenseFactory,
    SubscriptionPlanFactory,
    get_random_salesforce_id,
)


faker = FakerFactory.create()


def make_bound_subscription_form(
    title=faker.pystr(min_chars=1, max_chars=127),
    purchase_date=date.today(),
    start_date=date.today(),
    expiration_date=date.today() + timedelta(days=366),
    enterprise_customer_uuid=faker.uuid4(),
    enterprise_catalog_uuid=faker.uuid4(),
    netsuite_product_id=faker.random_int(),
    salesforce_opportunity_id=get_random_salesforce_id(),
    num_licenses=0,
    is_active=False,
    for_internal_use_only=False,
):
    """
    Builds a bound SubscriptionPlanForm
    """
    form_data = {
        'title': title,
        'purchase_date': purchase_date,
        'start_date': start_date,
        'expiration_date': expiration_date,
        'enterprise_customer_uuid': enterprise_customer_uuid,
        'enterprise_catalog_uuid': enterprise_catalog_uuid,
        'netsuite_product_id': netsuite_product_id,
        'salesforce_opportunity_id': salesforce_opportunity_id,
        'num_licenses': num_licenses,
        'is_active': is_active,
        'for_internal_use_only': for_internal_use_only,
    }
    return SubscriptionPlanForm(form_data)


def make_test_email_data():
    """
    Returns a dictionary of data needed to send emails
    """

    # Create a SubscriptionPlan and associate a batch of licenses using Factories
    subscription = SubscriptionPlanFactory()
    licenses = LicenseFactory.create_batch(6)
    subscription.licenses.set(licenses)

    custom_template_text = {
        'greeting': 'Hello',
        'closing': 'Goodbye',
    }

    email_recipient_list = [
        'boatymcboatface@mit.edu',
        'saul.goodman@bettercallsaul.com',
        't.soprano@badabing.net',
    ]

    # Use emails from list created above to create assigned licenses
    for lic, email in zip(licenses, email_recipient_list):
        lic.user_email = email
        lic.status = ASSIGNED
        lic.save()

    return {
        'subscription_plan': subscription,
        'licenses': licenses,
        'custom_template_text': custom_template_text,
        'email_recipient_list': email_recipient_list
    }


def assert_date_fields_correct(licenses, date_field_names, should_be_updated):
    """
    Helper that verifies that all of the given licenses have had the given date fields updated if applicable.

    If they should not have been updated, then it checks that the fields given by `date_field_names` is still None.
    """
    for license_obj in licenses:
        license_obj.refresh_from_db()
        if should_be_updated:
            for field_name in date_field_names:
                assert getattr(license_obj, field_name).date() == date.today()
        else:
            for field_name in date_field_names:
                assert getattr(license_obj, field_name) is None


def assert_license_fields_cleared(license_obj):
    """
    Helper function to verify that the appropriate fields on a license have been cleared out to None.

    Does not check that the `user_email` or `activation_key` is None as some workflows reset these for reassignment.
    """
    license_obj.refresh_from_db()
    assert license_obj.lms_user_id is None
    assert license_obj.last_remind_date is None
    assert license_obj.activation_date is None
    assert license_obj.assigned_date is None
    assert license_obj.revoked_date is None
