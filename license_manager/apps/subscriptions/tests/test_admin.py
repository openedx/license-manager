# pylint: disable=redefined-outer-name
from unittest import mock

import pytest
from django.contrib.admin.sites import AdminSite
from django.test import RequestFactory

from license_manager.apps.subscriptions.admin import (
    CustomerAgreementAdmin,
    SubscriptionPlanAdmin,
)
from license_manager.apps.subscriptions.forms import SubscriptionPlanForm
from license_manager.apps.subscriptions.models import (
    CustomerAgreement,
    SubscriptionPlan,
)
from license_manager.apps.subscriptions.tests.factories import (
    CustomerAgreementFactory,
    PlanTypeFactory,
    SubscriptionPlanFactory,
    UserFactory,
)
from license_manager.apps.subscriptions.tests.utils import (
    make_bound_customer_agreement_form,
    make_bound_subscription_form,
)


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
def test_licenses_subscription_modification():
    """
    Verify that creating a SubscriptionPlan creates its associated Licenses after it is created.
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
    form = make_bound_subscription_form(num_licenses=1)
    form.save()

    # save the form as a modify instead of create
    subscription_admin.save_model(request, subscription_plan, form, True)

    # The save_model() method should determine that licenses need to be created,
    # and then create them (synchronously in this case, since its a small number of licenses).
    subscription_plan.refresh_from_db()
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
