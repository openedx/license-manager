# pylint: disable=redefined-outer-name
from unittest import mock

import pytest
from django.contrib import messages
from django.contrib.admin.sites import AdminSite
from django.test import RequestFactory

from license_manager.apps.subscriptions.admin import (
    CustomerAgreementAdmin,
    SubscriptionPlanAdmin,
)
from license_manager.apps.subscriptions.models import (
    CustomerAgreement,
    SubscriptionPlan,
)
from license_manager.apps.subscriptions.tests.factories import (
    CustomerAgreementFactory,
    LicenseFactory,
    SubscriptionPlanFactory,
    UserFactory,
)
from license_manager.apps.subscriptions.tests.utils import (
    make_bound_customer_agreement_form,
    make_bound_subscription_form,
)
from license_manager.apps.subscriptions.utils import localized_utcnow

from ..constants import REVOKED


@pytest.mark.django_db
def test_licenses_subscription_creation():
    """
    Verify that creating a SubscriptionPlan creates its associated Licenses after it is created.
    """
    subscription_admin = SubscriptionPlanAdmin(SubscriptionPlan, AdminSite())
    request = RequestFactory()
    request.user = UserFactory()
    num_licenses = 5
    form = make_bound_subscription_form(num_licenses=num_licenses)
    obj = form.save()  # Get the object returned from saving the form to save to the database
    assert obj.licenses.count() == 0  # Verify no Licenses have been created yet
    change = False
    subscription_admin.save_model(request, obj, form, change)
    assert obj.licenses.count() == num_licenses


@pytest.mark.django_db
@mock.patch('license_manager.apps.subscriptions.admin.messages.add_message')
def test_subscription_licenses_create_action(mock_add_message):
    """
    Verify that running the create licenses action will create licenses.
    """
    # Setup an existing plan
    customer_agreement = CustomerAgreementFactory()
    subscription_plan = SubscriptionPlanFactory.create(
        customer_agreement=customer_agreement,
        desired_num_licenses=10,
    )
    assert subscription_plan.licenses.count() == 0  # Verify no Licenses have been created yet

    # setup the admin form
    subscription_admin = SubscriptionPlanAdmin(SubscriptionPlan, AdminSite())
    request = RequestFactory()
    request.user = UserFactory()

    # doesn't really matter what we put for num_licenses in here, save_model
    # will read the desired number of license from the existing object on save.
    form = make_bound_subscription_form(num_licenses=10)
    form.save()

    # save the form as a modify instead of create
    subscription_admin.save_model(request, subscription_plan, form, True)
    subscription_plan.refresh_from_db()
    # Desired number of licenses won't actually be created until we run the action
    assert subscription_plan.licenses.count() == 0

    # Now run the action...
    subscription_admin.create_actual_licenses_action(
        request,
        SubscriptionPlan.objects.filter(uuid=subscription_plan.uuid),
    )
    subscription_plan.refresh_from_db()
    # Actual number of licenses should now equal the desired number (ten)
    assert subscription_plan.licenses.count() == 10

    mock_add_message.assert_called_once_with(
        request, messages.SUCCESS, 'Successfully created license records for selected Subscription Plans.',
    )

    # check that freezing the plan means running the create licenses action has no effect
    subscription_plan.last_freeze_timestamp = localized_utcnow()
    subscription_plan.desired_num_licenses = 5000
    subscription_plan.save()

    subscription_admin.create_actual_licenses_action(
        request,
        SubscriptionPlan.objects.filter(uuid=subscription_plan.uuid),
    )
    subscription_plan.refresh_from_db()
    # Actual number of licenses should STILL equal 10, because the plan is frozen
    assert subscription_plan.licenses.count() == 10


@pytest.mark.django_db
@mock.patch('license_manager.apps.subscriptions.admin.toggle_auto_apply_licenses')
def test_select_subscription_for_auto_applied_licenses(mock_toggle_auto_apply_licenses):
    """
    Verify that selecting a SubscriptionPlan on a CustomerAgreement
    calls toggle_auto_apply_licenses.
    """
    customer_agreement_admin = CustomerAgreementAdmin(CustomerAgreement, AdminSite())
    request = RequestFactory()
    request.user = UserFactory()
    customer_agreement = CustomerAgreementFactory()
    subscription_plan = SubscriptionPlanFactory(customer_agreement=customer_agreement)
    customer_agreement_uuid = str(customer_agreement.uuid)
    subscription_uuid = str(subscription_plan.uuid)
    request.resolver_match = mock.Mock(kwargs={'object_id': customer_agreement_uuid})

    form = make_bound_customer_agreement_form(
        customer_agreement=customer_agreement,
        subscription_for_auto_applied_licenses=subscription_uuid
    )
    obj = form.save()  # Get the object returned from saving the form to save to the database
    change = True
    customer_agreement_admin.save_model(request, obj, form, change)

    args = mock_toggle_auto_apply_licenses.call_args[0]
    assert args[0] is customer_agreement_uuid
    assert args[1] is subscription_uuid


@pytest.mark.django_db
@mock.patch('license_manager.apps.subscriptions.admin.messages.add_message')
def test_delete_all_revoked_licenses(mock_add_message):
    """
    Verify that creating a SubscriptionPlan creates its associated Licenses after it is created.
    """
    subscription_admin = SubscriptionPlanAdmin(SubscriptionPlan, AdminSite())
    request = RequestFactory()
    request.user = UserFactory()

    # Setup an existing plan with revoked licenses
    customer_agreement = CustomerAgreementFactory()
    subscription_plan = SubscriptionPlanFactory.create(
        customer_agreement=customer_agreement,
    )
    LicenseFactory.create_batch(
        10,
        subscription_plan=subscription_plan,
        status=REVOKED,
    )
    subscription_plan.refresh_from_db()
    assert subscription_plan.revoked_licenses.count() == 10

    # Now use the admin action to delete all revoked licenses for the plan
    subscription_admin.delete_all_revoked_licenses(
        request,
        SubscriptionPlan.objects.filter(uuid=subscription_plan.uuid),
    )
    subscription_plan.refresh_from_db()
    assert subscription_plan.revoked_licenses.count() == 0

    mock_add_message.assert_called_once_with(
        request, messages.SUCCESS, f"Successfully deleted revoked licenses for plans ['{subscription_plan.title}'].",
    )
