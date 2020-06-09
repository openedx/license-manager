"""
Testing utilities for the Subscriptions app.
"""
from datetime import date, timedelta

from faker import Factory as FakerFactory

from license_manager.apps.subscriptions.forms import SubscriptionPlanForm


faker = FakerFactory.create()


def make_bound_subscription_form(
    title=faker.pystr(min_chars=1, max_chars=127),
    purchase_date=date.today(),
    start_date=date.today(),
    expiration_date=date.today() + timedelta(days=366),
    enterprise_customer_uuid=faker.uuid4(),
    enterprise_catalog_uuid=faker.uuid4(),
    num_licenses=0,
    is_active=False
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
        'num_licenses': num_licenses,
        'is_active': is_active
    }
    return SubscriptionPlanForm(form_data)
