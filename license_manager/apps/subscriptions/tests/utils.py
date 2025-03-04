"""
Testing utilities for the Subscriptions app.
"""
from datetime import timedelta

from faker import Factory as FakerFactory

from license_manager.apps.subscriptions.constants import (
    ASSIGNED,
    LicenseTypesToRenew,
)
from license_manager.apps.subscriptions.forms import (
    CustomerAgreementAdminForm,
    SubscriptionPlanForm,
    SubscriptionPlanRenewalForm,
)
from license_manager.apps.subscriptions.tests.factories import (
    CustomerAgreementFactory,
    LicenseFactory,
    PlanTypeFactory,
    ProductFactory,
    SubscriptionPlanFactory,
    get_random_salesforce_id,
)
from license_manager.apps.subscriptions.utils import localized_utcnow


faker = FakerFactory.create()


def make_bound_subscription_form(
    title=faker.pystr(min_chars=1, max_chars=127),
    start_date=localized_utcnow(),
    expiration_date=localized_utcnow() + timedelta(days=366),
    enterprise_catalog_uuid=faker.uuid4(),
    enterprise_customer_uuid=faker.uuid4(),
    salesforce_opportunity_line_item=get_random_salesforce_id(),
    num_licenses=0,
    is_active=False,
    for_internal_use_only=False,
    has_product=True,
    is_sf_id_required=False,
    has_customer_agreement=True,
    customer_agreement_has_default_catalog=True,
    change_reason="new"
):
    """
    Builds a bound SubscriptionPlanForm
    """
    if customer_agreement_has_default_catalog:
        customer_agreement = CustomerAgreementFactory(enterprise_customer_uuid=enterprise_customer_uuid)
    else:
        customer_agreement = CustomerAgreementFactory(
            enterprise_customer_uuid=enterprise_customer_uuid,
            default_enterprise_catalog_uuid=None
        )

    product = ProductFactory(plan_type=PlanTypeFactory(sf_id_required=is_sf_id_required))

    form_data = {
        'title': title,
        'start_date': start_date,
        'expiration_date': expiration_date,
        'enterprise_catalog_uuid': enterprise_catalog_uuid,
        'product': product.id if has_product else None,
        'salesforce_opportunity_line_item': salesforce_opportunity_line_item,
        'num_licenses': num_licenses,
        'is_active': is_active,
        'for_internal_use_only': for_internal_use_only,
        'customer_agreement': str(customer_agreement.uuid) if has_customer_agreement else None,
        'change_reason': change_reason
    }
    return SubscriptionPlanForm(form_data)


def make_bound_subscription_plan_renewal_form(
    prior_subscription_plan,
    effective_date,
    renewed_expiration_date,
    processed=False,
    salesforce_opportunity_id=get_random_salesforce_id(),
    license_types_to_copy=LicenseTypesToRenew.ASSIGNED_AND_ACTIVATED,
):
    """
    Builds a bound SubscriptionPlanRenewalForm
    """
    form_data = {
        'prior_subscription_plan': prior_subscription_plan.uuid,
        'effective_date': effective_date,
        'renewed_expiration_date': renewed_expiration_date,
        'processed': processed,
        'number_of_licenses': faker.random_int(),
        'salesforce_opportunity_id': salesforce_opportunity_id,
        'license_types_to_copy': license_types_to_copy,
    }
    return SubscriptionPlanRenewalForm(form_data)


def make_bound_customer_agreement_form(
    customer_agreement,
    default_enterprise_catalog_uuid=None,
    disable_expiration_notifications=False,
    license_duration_before_purge=90,
    subscription_for_auto_applied_licenses=''
):
    """
    Builds a bound CustomerAgreementAdminForm
    """
    form_data = {
        'customer_agreement_uuid': str(customer_agreement.uuid),
        'enterprise_customer_uuid': customer_agreement.enterprise_customer_uuid,
        'default_enterprise_catalog_uuid': default_enterprise_catalog_uuid,
        'disable_expiration_notifications': disable_expiration_notifications,
        'license_duration_before_purge_0': license_duration_before_purge,
        'subscription_for_auto_applied_licenses': subscription_for_auto_applied_licenses,
        'enterprise_customer_slug': 'test-slug'
    }
    return CustomerAgreementAdminForm(form_data, instance=customer_agreement)


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
                assert getattr(license_obj, field_name) == localized_utcnow()
        else:
            for field_name in date_field_names:
                assert getattr(license_obj, field_name) is None


def assert_license_fields_cleared(license_obj):
    """
    Helper function to verify that the appropriate fields on a license have been cleared out to None.
    """
    license_obj.refresh_from_db()
    assert license_obj.lms_user_id is None
    assert license_obj.activation_date is None
    assert license_obj.revoked_date is None

    if license_obj.status != ASSIGNED:
        assert license_obj.last_remind_date is None
        assert license_obj.assigned_date is None
        assert license_obj.activation_key is None
        assert license_obj.user_email is None


def assert_pii_cleared(license_obj):
    """
    Helper to verify that pii on a license has been cleared.
    """
    assert license_obj.user_email is None


def assert_historical_pii_cleared(license_obj):
    """
    Helper to verify that pii from the license's history records has been cleared.
    """
    for history_record in license_obj.history.all():
        assert history_record.user_email is None
