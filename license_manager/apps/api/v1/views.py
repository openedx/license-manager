from django_filters.rest_framework import DjangoFilterBackend
from rest_framework import filters, viewsets

from edx_rbac.mixins import PermissionRequiredForListingMixin

from license_manager.apps.api.serializers import (
    LicenseSerializer,
    SubscriptionPlanSerializer,
)
from license_manager.apps.subscriptions import constants
from license_manager.apps.subscriptions.models import (
    License,
    SubscriptionsRoleAssignment,
    SubscriptionPlan,
)


class SubscriptionViewSet(PermissionRequiredForListingMixin, viewsets.ReadOnlyModelViewSet):
    """ Viewset for read operations on SubscriptionPlans."""
    lookup_field = 'uuid'
    lookup_url_kwarg = 'subscription_uuid'
    serializer_class = SubscriptionPlanSerializer
    permission_required = constants.SUBSCRIPTIONS_ADMIN_ACCESS_PERMISSION

    # fields that control permissions for 'list' actions
    list_lookup_field = 'enterprise_customer_uuid'
    allowed_roles = [constants.SUBSCRIPTIONS_ADMIN_ROLE]
    role_assignment_class = SubscriptionsRoleAssignment

    @property
    def requested_enterprise_uuid(self):
        return self.request.query_params.get('enterprise_customer_uuid')

    @property
    def requested_subscription_uuid(self):
        return self.kwargs.get('subscription_uuid')

    def get_permission_object(self):
        """
        Used for "retrieve" actions.  Determines which SubscriptionPlan instances
        to check for role-based permissions against.
        """
        try:
            return SubscriptionPlan.objects.get(uuid=self.requested_subscription_uuid)
        except SubscriptionPlan.DoesNotExist:
            return None

    @property
    def base_queryset(self):
        """
        Required by the `PermissionRequiredForListingMixin`.
        For non-list actions, this is what's returned by `get_queryset()`.
        For list actions, some non-strict subset of this is what's returned by `get_queryset()`.
        """
        if self.requested_enterprise_uuid:
            return SubscriptionPlan.objects.filter(enterprise_customer_uuid=self.requested_enterprise_uuid)
        return SubscriptionPlan.objects.all()


class LicenseViewSet(PermissionRequiredForListingMixin, viewsets.ReadOnlyModelViewSet):
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
    permission_required = constants.SUBSCRIPTIONS_ADMIN_ACCESS_PERMISSION

    # The fields that control permissions for 'list' actions.
    # Roles are granted on specific enterprise identifiers, so we have to join
    # from this model to SubscriptionPlan to find the corresponding customer identifier.
    list_lookup_field = 'subscription_plan__enterprise_customer_uuid'
    allowed_roles = [constants.SUBSCRIPTIONS_ADMIN_ROLE]
    role_assignment_class = SubscriptionsRoleAssignment

    @property
    def requested_subscription_uuid(self):
        return self.kwargs.get('subscription_uuid')

    def get_permission_object(self):
        try:
            return SubscriptionPlan.objects.get(uuid=self.requested_subscription_uuid)
        except SubscriptionPlan.DoesNotExist:
            return None

    @property
    def base_queryset(self):
        """
        Required by the `PermissionRequiredForListingMixin`.
        For non-list actions, this is what's returned by `get_queryset()`.
        For list actions, some non-strict subset of this is what's returned by `get_queryset()`.
        """
        if self.requested_subscription_uuid:
            return License.objects.filter(subscription_plan=self.requested_subscription_uuid)
        return License.objects.all()
