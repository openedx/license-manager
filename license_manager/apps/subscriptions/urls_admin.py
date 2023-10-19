from dal import autocomplete
from django.urls import re_path as url

from .models import SubscriptionPlan


class FilteredSubscriptionPlanView(autocomplete.Select2QuerySetView):
    """
    Supports filtering of LicenseTransferJob SubscriptionPlan
    choices to only those plans associated with the selected
    customer agreement.

    This is used by the LicenseTransferJobAdminForm.Meta.widgets
    property, which forwards the customer_agreement identifier
    into this view, so that it can filter the queryset of
    available subscription plans to only those plans
    associated with the selected customer agreement.
    """
    def get_queryset(self):
        queryset = super().get_queryset()
        customer_agreement = self.forwarded.get('customer_agreement', None)
        if customer_agreement:
            queryset = queryset.filter(customer_agreement=customer_agreement)
        return queryset


urlpatterns = [
    url(
        'filtered-subscription-plan-admin/$',
        FilteredSubscriptionPlanView.as_view(model=SubscriptionPlan),
        name='filtered_subscription_plan_admin',
    ),
]
