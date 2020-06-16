from datetime import datetime

from django.core.exceptions import ObjectDoesNotExist
from django.db.models import Count
from django_filters.rest_framework import DjangoFilterBackend
from rest_framework import filters, status, viewsets
from rest_framework.decorators import action
from rest_framework.response import Response

from license_manager.apps.api.serializers import (
    CustomTextSerializer,
    LicenseEmailSerializer,
    LicenseSerializer,
    SubscriptionPlanSerializer,
)
from license_manager.apps.subscriptions import emails
from license_manager.apps.subscriptions.constants import ASSIGNED
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
    filter_backends = [DjangoFilterBackend, filters.OrderingFilter, filters.SearchFilter]
    ordering_fields = [
        'user_email',
        'status',
        'activation_date',
        'last_remind_date',
    ]
    search_fields = ['user_email']
    filterset_fields = ['status']

    def get_queryset(self):
        """
        Restricts licenses to those only linked with the subscription plan specified in the route.

        TODO: Restrict this to only those valid with the user's enterprise when we add rbac
        """
        return License.objects.filter(subscription_plan=self._get_subscription_plan())

    def get_serializer_class(self):
        if self.action == 'remind':
            return LicenseEmailSerializer
        if self.action == 'remind_all':
            return CustomTextSerializer
        return LicenseSerializer

    def _get_subscription_plan(self):
        """
        Helper that returns the subscription plan specified by `subscription_uuid` in the request.
        """
        return SubscriptionPlan.objects.get(uuid=self.kwargs['subscription_uuid'])

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
        try:
            user_license = License.objects.get(user_email=user_email, status=ASSIGNED)
        except ObjectDoesNotExist:
            msg = 'Could not find any licenses pending activation that are associated with the email: {}'.format(
                user_email,
            )
            return Response(msg, status=status.HTTP_404_NOT_FOUND)

        subscription_plan = self._get_subscription_plan()
        # Send activation reminder email
        emails.send_reminder_emails(
            self._get_custom_text(request.data),
            [user_email],
            subscription_plan,
        )

        # Set last remind date to now
        user_license.last_remind_date = datetime.now()
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
        pending_licenses = License.objects.filter(subscription_plan=subscription_plan, status=ASSIGNED)
        if not pending_licenses:
            return Response('Could not find any licenses pending activation', status=status.HTTP_404_NOT_FOUND)

        pending_user_emails = [license.user_email for license in pending_licenses]
        # Send activation reminder email to all pending users
        emails.send_reminder_emails(
            self._get_custom_text(request.data),
            pending_user_emails,
            subscription_plan,
        )

        # Set last remind date to now for all pending licenses
        for pending_license in pending_licenses:
            pending_license.last_remind_date = datetime.now()
        License.objects.bulk_update(pending_licenses, ['last_remind_date'])

        return Response(status=status.HTTP_200_OK)

    @action(detail=False, methods=['get'])
    def overview(self, request, subscription_uuid=None):
        queryset = self.filter_queryset(self.get_queryset())
        queryset_values = queryset.values('status').annotate(count=Count('status')).order_by('-count')
        license_overview = list(queryset_values)
        return Response(license_overview, status=status.HTTP_200_OK)
