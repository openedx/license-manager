from django_filters.rest_framework import DjangoFilterBackend
from rest_framework import filters, viewsets

from license_manager.apps.api.serializers import (
    LicenseSerializer,
    SubscriptionPlanSerializer,
)
from license_manager.apps.subscriptions.models import License, SubscriptionPlan


class SubscriptionViewSet(viewsets.ReadOnlyModelViewSet):
    """ Viewset for read operations on SubscriptionPlans."""
    lookup_field = 'uuid'
    lookup_url_kwarg = 'subscription_uuid'
    serializer_class = SubscriptionPlanSerializer

    def get_queryset(self):
        """
        Gets the queryset of subscriptions available to the requester and their enterprise.

        For the detail view, all subscriptions are currently in the queryset, but this will change when we add rbac.
        The enterprise is specified by the `enterprise_customer_uuid` query parameter. This query parameter is useable
        only by staff users, with non-staff users already restricted from this viewset. Additionally, staff users are
        only able to get information about subscriptions associated with enterprises for which they are admins.

        TODO: Some of this functionality is not currently implemented, and will need to be done as part of the work to
        add edx-rbac permissions to the service.

        Returns:
            Queryset: The queryset of SubscriptionPlans the user has access to.
        """
        request_action = getattr(self, 'action', None)
        if request_action == 'retrieve':
            return SubscriptionPlan.objects.all()

        user = self.request.user
        if user.is_superuser:
            return SubscriptionPlan.objects.all()

        enterprise_customer_uuid = self.request.query_params.get('enterprise_customer_uuid', None)
        if not enterprise_customer_uuid:
            return SubscriptionPlan.objects.none()

        return SubscriptionPlan.objects.filter(enterprise_customer_uuid=enterprise_customer_uuid)


class LicenseViewSet(viewsets.ReadOnlyModelViewSet):
    """ Viewset for read operations on Licenses."""
    lookup_field = 'uuid'
    lookup_url_kwarg = 'license_uuid'
    serializer_class = LicenseSerializer
    filter_backends = [DjangoFilterBackend, filters.OrderingFilter]
    ordering_fields = [
        'user_email',
        'status',
        'activation_date',
        'last_remind_date',
    ]
    filterset_fields = [
        'user_email',
        'status'
    ]

    def get_queryset(self):
        """
        Restricts licenses to those only linked with the subscription plan specified in the route.

        TODO: Restrict this to only those valid with the user's enterprise when we add rbac
        """
        return License.objects.filter(subscription_plan=self.kwargs['subscription_uuid'])
