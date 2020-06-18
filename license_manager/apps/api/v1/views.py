import logging

from django.core.exceptions import ObjectDoesNotExist
from django.db.models import Count
from django_filters.rest_framework import DjangoFilterBackend
from edx_rbac.mixins import PermissionRequiredForListingMixin
from edx_rest_framework_extensions.auth.jwt.authentication import (
    JwtAuthentication,
)
from rest_framework import filters, permissions, status, viewsets
from rest_framework.authentication import SessionAuthentication
from rest_framework.decorators import action
from rest_framework.response import Response

from license_manager.apps.api import serializers
from license_manager.apps.api.tasks import (
    send_activation_email_task,
    send_reminder_email_task,
)
from license_manager.apps.api.utils import localized_utcnow
from license_manager.apps.subscriptions import constants
from license_manager.apps.subscriptions.models import (
    License,
    SubscriptionPlan,
    SubscriptionsRoleAssignment,
)


logger = logging.getLogger(__name__)


class SubscriptionViewSet(PermissionRequiredForListingMixin, viewsets.ReadOnlyModelViewSet):
    """ Viewset for read operations on SubscriptionPlans."""
    authentication_classes = [JwtAuthentication, SessionAuthentication]
    permission_classes = [permissions.IsAuthenticated]

    lookup_field = 'uuid'
    lookup_url_kwarg = 'subscription_uuid'
    serializer_class = serializers.SubscriptionPlanSerializer
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
        queryset = SubscriptionPlan.objects.all()
        if self.requested_enterprise_uuid:
            queryset = SubscriptionPlan.objects.filter(enterprise_customer_uuid=self.requested_enterprise_uuid)
        return queryset.order_by('-start_date')


class LicenseViewSet(PermissionRequiredForListingMixin, viewsets.ReadOnlyModelViewSet):
    """ Viewset for read operations on Licenses."""
    authentication_classes = [JwtAuthentication, SessionAuthentication]
    permission_classes = [permissions.IsAuthenticated]

    lookup_field = 'uuid'
    lookup_url_kwarg = 'license_uuid'
    filter_backends = [DjangoFilterBackend, filters.OrderingFilter, filters.SearchFilter]
    ordering_fields = [
        'user_email',
        'status',
        'activation_date',
        'last_remind_date',
    ]
    search_fields = ['user_email']
    filterset_fields = ['status']
    permission_required = constants.SUBSCRIPTIONS_ADMIN_ACCESS_PERMISSION

    # The fields that control permissions for 'list' actions.
    # Roles are granted on specific enterprise identifiers, so we have to join
    # from this model to SubscriptionPlan to find the corresponding customer identifier.
    list_lookup_field = 'subscription_plan__enterprise_customer_uuid'
    allowed_roles = [constants.SUBSCRIPTIONS_ADMIN_ROLE]
    role_assignment_class = SubscriptionsRoleAssignment

    def get_permission_object(self):
        """
        The requesting user needs access to the license's SubscriptionPlan
        in order to access the license.
        """
        return self._get_subscription_plan()

    @property
    def base_queryset(self):
        """
        Required by the `PermissionRequiredForListingMixin`.
        For non-list actions, this is what's returned by `get_queryset()`.
        For list actions, some non-strict subset of this is what's returned by `get_queryset()`.
        """
        return License.objects.filter(subscription_plan=self._get_subscription_plan()).order_by('-activation_date')

    def get_serializer_class(self):
        if self.action == 'assign':
            return serializers.LicenseEmailSerializer
        if self.action == 'remind':
            return serializers.LicenseSingleEmailSerializer
        if self.action == 'remind_all':
            return serializers.CustomTextSerializer
        return serializers.LicenseSerializer

    def _get_subscription_plan(self):
        """
        Helper that returns the subscription plan specified by `subscription_uuid` in the request.
        """
        try:
            return SubscriptionPlan.objects.get(uuid=self.kwargs['subscription_uuid'])
        except SubscriptionPlan.DoesNotExist:
            return None

    def _get_custom_text(self, data):
        """
        Returns a dictionary with the custom text given in the POST data.
        """
        return {
            'greeting': data.get('greeting', ''),
            'closing': data.get('closing', ''),
        }

    def _validate_data(self, data):
        """
        Helper that validates the data sent in from a POST request.

        Raises an exception with the error in the serializer if the data is invalid.
        """
        serializer_class = self.get_serializer_class()
        serializer = serializer_class(data=data)
        serializer.is_valid(raise_exception=True)

    @action(detail=False, methods=['post'])
    def assign(self, request, subscription_uuid=None):
        # Validate the user_emails and text sent in the data
        self._validate_data(request.data)
        # Dedupe emails before turning back into a list for indexing
        user_emails = list(set(request.data.get('user_emails', [])))

        # Make sure there are enough unassigned licenses
        num_user_emails = len(user_emails)
        subscription_plan = self._get_subscription_plan()
        num_unassigned_licenses = subscription_plan.unassigned_licenses.count()
        if num_user_emails > num_unassigned_licenses:
            msg = (
                'There are not enough unassigned licenses to complete your request.'
                'You attempted to assign {} licenses, but there are only {} available.'
            ).format(num_user_emails, num_unassigned_licenses)
            return Response(msg, status=status.HTTP_400_BAD_REQUEST)

        # Make sure none of the provided emails have already been associated with a license in the subscription
        already_associated_emails = list(
            subscription_plan.licenses.filter(user_email__in=user_emails).values_list('user_email', flat=True)
        )
        if already_associated_emails:
            msg = 'The following user emails are already associated with a license: {}'.format(
                already_associated_emails,
            )
            return Response(msg, status=status.HTTP_400_BAD_REQUEST)

        # Get a queryset of only the number of licenses we need to assign
        unassigned_licenses = subscription_plan.unassigned_licenses[:num_user_emails]
        for unassigned_license, email in zip(unassigned_licenses, user_emails):
            # Assign each email to a license and mark the license as assigned
            unassigned_license.user_email = email
            unassigned_license.status = constants.ASSIGNED
        # Efficiently update the licenses in bulk
        License.objects.bulk_update(unassigned_licenses, ['user_email', 'status'])

        # Send activation emails
        send_activation_email_task.delay(
            self._get_custom_text(request.data),
            user_emails,
            subscription_uuid,
        )

        return Response(status=status.HTTP_200_OK)

    @action(detail=False, methods=['post'])
    def remind(self, request, subscription_uuid=None):
        """
        Given a single email in the POST data, sends a reminder email that they have a license pending activation.

        This endpoint reminds users by sending an email to the given email address, if there is a license which has not
        yet been activated that is associated with that email address.
        Additionally, updates the license to reflect that a reminder was just sent.

        # TODO: Restrict to enterprise admins with edx-rbac implementation
        """
        # Validate the user_email and text sent in the data
        self._validate_data(request.data)

        # Make sure there is a license that is still pending activation associated with the given email
        user_email = request.data.get('user_email')
        subscription_plan = self._get_subscription_plan()
        try:
            user_license = License.objects.get(
                subscription_plan=subscription_plan,
                user_email=user_email,
                status=constants.ASSIGNED,
            )
        except ObjectDoesNotExist:
            msg = 'Could not find any licenses pending activation that are associated with the email: {}'.format(
                user_email,
            )
            return Response(msg, status=status.HTTP_404_NOT_FOUND)

        # Send activation reminder email
        send_reminder_email_task.delay(
            self._get_custom_text(request.data),
            [user_email],
            subscription_uuid,
        )

        # Set last remind date to now
        user_license.last_remind_date = localized_utcnow()
        user_license.save()

        return Response(status=status.HTTP_200_OK)

    @action(detail=False, methods=['post'], url_path='remind-all')
    def remind_all(self, request, subscription_uuid=None):
        """
        Reminds all users in the subscription who have a pending license that their license is awaiting activation.

        Additionally, updates all pending licenses to reflect that a reminder was just sent.
        """
        # Validate the text sent in the data
        self._validate_data(request.data)

        subscription_plan = self._get_subscription_plan()
        pending_licenses = subscription_plan.licenses.filter(status=constants.ASSIGNED)
        if not pending_licenses:
            return Response('Could not find any licenses pending activation', status=status.HTTP_404_NOT_FOUND)

        pending_user_emails = [license.user_email for license in pending_licenses]
        # Send activation reminder email to all pending users
        send_reminder_email_task.delay(
            self._get_custom_text(request.data),
            pending_user_emails,
            subscription_uuid,
        )

        # Set last remind date to now for all pending licenses
        for pending_license in pending_licenses:
            pending_license.last_remind_date = localized_utcnow()
        License.objects.bulk_update(pending_licenses, ['last_remind_date'])

        return Response(status=status.HTTP_200_OK)

    @action(detail=False, methods=['get'])
    def overview(self, request, subscription_uuid=None):
        queryset = self.filter_queryset(self.get_queryset())
        queryset_values = queryset.values('status').annotate(count=Count('status')).order_by('-count')
        license_overview = list(queryset_values)
        return Response(license_overview, status=status.HTTP_200_OK)
