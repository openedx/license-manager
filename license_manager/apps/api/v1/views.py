import logging
import uuid
from collections import OrderedDict
from uuid import uuid4

from celery import chain
from django.contrib.auth import get_user_model
from django.core.exceptions import ObjectDoesNotExist
from django.db.models import Count
from django.utils.functional import cached_property
from django_filters.rest_framework import DjangoFilterBackend
from edx_rbac.decorators import permission_required
from edx_rbac.mixins import PermissionRequiredForListingMixin
from edx_rest_framework_extensions.auth.jwt.authentication import (
    JwtAuthentication,
)
from rest_framework import filters, permissions, status, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import ParseError
from rest_framework.mixins import ListModelMixin
from rest_framework.pagination import PageNumberPagination
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework_csv.renderers import CSVRenderer
from simplejson.errors import JSONDecodeError

from license_manager.apps.api import serializers, utils
from license_manager.apps.api.filters import LicenseStatusFilter
from license_manager.apps.api.permissions import CanRetireUser
from license_manager.apps.api.tasks import (
    activation_email_task,
    link_learners_to_enterprise_task,
    send_onboarding_email_task,
    send_reminder_email_task,
)
from license_manager.apps.api_client.enterprise import EnterpriseApiClient
from license_manager.apps.subscriptions import constants
from license_manager.apps.subscriptions.api import revoke_license
from license_manager.apps.subscriptions.exceptions import LicenseRevocationError
from license_manager.apps.subscriptions.models import (
    CustomerAgreement,
    License,
    SubscriptionPlan,
    SubscriptionsRoleAssignment,
)
from license_manager.apps.subscriptions.utils import (
    chunks,
    get_license_activation_link,
    localized_utcnow,
)


logger = logging.getLogger(__name__)


class CustomerAgreementViewSet(PermissionRequiredForListingMixin, viewsets.ReadOnlyModelViewSet):
    """ Viewset for read operations on CustomerAgreements. """

    authentication_classes = [JwtAuthentication]
    permission_classes = [permissions.IsAuthenticated]

    lookup_field = 'uuid'
    lookup_url_kwarg = 'customer_agreement_uuid'
    serializer_class = serializers.CustomerAgreementSerializer
    permission_required = constants.SUBSCRIPTIONS_ADMIN_LEARNER_ACCESS_PERMISSION

    # fields that control permissions for 'list' actions
    list_lookup_field = 'enterprise_customer_uuid'
    allowed_roles = [constants.SUBSCRIPTIONS_ADMIN_ROLE, constants.SUBSCRIPTIONS_LEARNER_ROLE]
    role_assignment_class = SubscriptionsRoleAssignment

    @property
    def requested_enterprise_uuid(self):
        enterprise_customer_uuid = self.request.query_params.get('enterprise_customer_uuid')
        if not enterprise_customer_uuid:
            return None
        try:
            return uuid.UUID(enterprise_customer_uuid)
        except ValueError as exc:
            raise ParseError(f'{enterprise_customer_uuid} is not a valid uuid.') from exc

    @property
    def requested_customer_agreement_uuid(self):
        return self.kwargs.get('customer_agreement_uuid')

    def get_permission_object(self):
        """
        Used for "retrieve" actions. Determines the context (enterprise UUID) to check
        against for role-based permissions.
        """
        if self.requested_enterprise_uuid:
            return self.requested_enterprise_uuid

        try:
            customer_agreement = CustomerAgreement.objects.get(uuid=self.requested_customer_agreement_uuid)
            return customer_agreement.enterprise_customer_uuid
        except CustomerAgreement.DoesNotExist:
            return None

    @property
    def base_queryset(self):
        """
        Required by the `PermissionRequiredForListingMixin`.
        For non-list actions, this is what's returned by `get_queryset()`.
        For list actions, some non-strict subset of this is what's returned by `get_queryset()`.
        """
        kwargs = {}
        if self.requested_enterprise_uuid:
            kwargs.update({'enterprise_customer_uuid': self.requested_enterprise_uuid})
        if self.requested_customer_agreement_uuid:
            kwargs.update({'uuid': self.requested_customer_agreement_uuid})

        return CustomerAgreement.objects.filter(**kwargs)


class LearnerSubscriptionViewSet(PermissionRequiredForListingMixin, viewsets.ReadOnlyModelViewSet):
    """ Viewset for read operations on LearnerSubscriptionPlans."""
    authentication_classes = [JwtAuthentication]
    permission_classes = [permissions.IsAuthenticated]

    lookup_field = 'uuid'
    lookup_url_kwarg = 'subscription_uuid'
    serializer_class = serializers.SubscriptionPlanSerializer
    permission_required = constants.SUBSCRIPTIONS_ADMIN_LEARNER_ACCESS_PERMISSION

    # fields that control permissions for 'list' actions
    list_lookup_field = 'customer_agreement__enterprise_customer_uuid'
    allowed_roles = [constants.SUBSCRIPTIONS_ADMIN_ROLE, constants.SUBSCRIPTIONS_LEARNER_ROLE]
    role_assignment_class = SubscriptionsRoleAssignment

    @property
    def requested_enterprise_uuid(self):
        enterprise_customer_uuid = self.request.query_params.get('enterprise_customer_uuid')
        if not enterprise_customer_uuid:
            return None
        try:
            return uuid.UUID(enterprise_customer_uuid)
        except ValueError as exc:
            raise ParseError(f'{enterprise_customer_uuid} is not a valid uuid.') from exc

    @property
    def requested_subscription_uuid(self):
        return self.kwargs.get('subscription_uuid')

    def get_permission_object(self):
        """
        Used for "retrieve" actions. Determines the context (enterprise UUID) to check
        against for role-based permissions.
        """
        try:
            subscription_plan = SubscriptionPlan.objects.get(uuid=self.requested_subscription_uuid)
            return subscription_plan.customer_agreement.enterprise_customer_uuid
        except SubscriptionPlan.DoesNotExist:
            return None

    @property
    def base_queryset(self):
        """
        Required by the `PermissionRequiredForListingMixin`.
        For non-list actions, this is what's returned by `get_queryset()`.
        For list actions, some non-strict subset of this is what's returned by `get_queryset()`.
        """
        if not self.requested_enterprise_uuid:
            return SubscriptionPlan.objects.none()

        return SubscriptionPlan.objects.filter(
            customer_agreement__enterprise_customer_uuid=self.requested_enterprise_uuid,
            is_active=True
        ).order_by('-start_date')


class SubscriptionViewSet(LearnerSubscriptionViewSet):
    """ Viewset for Admin only read operations on SubscriptionPlans."""
    permission_required = constants.SUBSCRIPTIONS_ADMIN_ACCESS_PERMISSION
    allowed_roles = [constants.SUBSCRIPTIONS_ADMIN_ROLE]

    @property
    def base_queryset(self):
        """
        Required by the `PermissionRequiredForListingMixin`.
        For non-list actions, this is what's returned by `get_queryset()`.
        For list actions, some non-strict subset of this is what's returned by `get_queryset()`.
        """
        queryset = SubscriptionPlan.objects.all()
        if self.requested_enterprise_uuid:
            queryset = SubscriptionPlan.objects.filter(
                customer_agreement__enterprise_customer_uuid=self.requested_enterprise_uuid,
                is_active=True,
            )
        return queryset.order_by('-start_date')


class LearnerLicenseViewSet(PermissionRequiredForListingMixin, viewsets.ReadOnlyModelViewSet):
    """
    Viewset for learner read operations on Licenses.

    Note: This Viewset's endpoint is part of the subscription SimpleNestedRouter - it is
    only intended for retrieving a single License. To obtain all Licenses for a given user
    customer pair, use LearnerLicensesViewSet.
    """
    authentication_classes = [JwtAuthentication]
    permission_classes = [permissions.IsAuthenticated]

    filter_backends = [DjangoFilterBackend, filters.OrderingFilter, filters.SearchFilter]
    ordering_fields = [
        'user_email',
        'status',
        'activation_date',
        'last_remind_date',
    ]
    search_fields = ['user_email']
    filter_class = LicenseStatusFilter
    permission_required = constants.SUBSCRIPTIONS_ADMIN_LEARNER_ACCESS_PERMISSION

    # The fields that control permissions for 'list' actions.
    # Roles are granted on specific enterprise identifiers, so we have to join
    # from this model to SubscriptionPlan to find the corresponding customer identifier.
    list_lookup_field = 'subscription_plan__customer_agreement__enterprise_customer_uuid'
    allowed_roles = [constants.SUBSCRIPTIONS_ADMIN_ROLE, constants.SUBSCRIPTIONS_LEARNER_ROLE]
    role_assignment_class = SubscriptionsRoleAssignment

    def get_permission_object(self):
        """
        The requesting user needs access to the license's SubscriptionPlan
        in order to access the license.
        """
        subscription_plan = self._get_subscription_plan()
        if not subscription_plan:
            return None

        return subscription_plan.customer_agreement.enterprise_customer_uuid

    def get_serializer_class(self):
        if self.action == 'assign':
            return serializers.CustomTextWithMultipleEmailsSerializer
        if self.action == 'remind':
            return serializers.CustomTextWithSingleEmailSerializer
        if self.action == 'remind_all':
            return serializers.CustomTextSerializer
        if self.action == 'revoke':
            return serializers.SingleEmailSerializer
        return serializers.LicenseSerializer

    @property
    def base_queryset(self):
        """
        Required by the `PermissionRequiredForListingMixin`.
        For non-list actions, this is what's returned by `get_queryset()`.
        For list actions, some non-strict subset of this is what's returned by `get_queryset()`.
        """
        return License.objects.filter(
            subscription_plan=self._get_subscription_plan(),
            user_email=self.request.user.email,
        ).exclude(status=constants.REVOKED)

    def _get_subscription_plan(self):
        """
        Helper that returns the subscription plan specified by `subscription_uuid` in the request.
        """
        subscription_uuid = self.kwargs.get('subscription_uuid')
        if not subscription_uuid:
            return None

        try:
            return SubscriptionPlan.objects.get(uuid=subscription_uuid)
        except SubscriptionPlan.DoesNotExist:
            return None


class LearnerLicensesViewSet(PermissionRequiredForListingMixin, ListModelMixin, viewsets.GenericViewSet):
    """
    This Viewset allows read operations of all Licenses for a given user-customer pair.
    """
    authentication_classes = [JwtAuthentication]
    filter_backends = [DjangoFilterBackend, filters.OrderingFilter, filters.SearchFilter]
    filter_class = LicenseStatusFilter
    ordering_fields = [
        'user_email',
        'status',
        'activation_date',
        'last_remind_date',
    ]
    permission_classes = [permissions.IsAuthenticated]
    permission_required = constants.SUBSCRIPTIONS_ADMIN_LEARNER_ACCESS_PERMISSION
    search_fields = ['user_email']
    serializer_class = serializers.LicenseSerializer

    # The fields that control permissions for 'list' actions.
    # Roles are granted on specific enterprise identifiers, so we have to join
    # from this model to SubscriptionPlan to find the corresponding customer identifier.
    list_lookup_field = 'subscription_plan__customer_agreement__enterprise_customer_uuid'
    allowed_roles = [constants.SUBSCRIPTIONS_ADMIN_ROLE, constants.SUBSCRIPTIONS_LEARNER_ROLE]
    role_assignment_class = SubscriptionsRoleAssignment

    @property
    def enterprise_customer_uuid(self):
        return self.request.query_params.get('enterprise_customer_uuid')

    def get_permission_object(self):
        """
        The requesting user needs access to the specified Customer in order to access the Licenses.
        """
        return self.enterprise_customer_uuid

    def list(self, request, *args, **kwargs):
        if not self.enterprise_customer_uuid:
            msg = 'missing enterprise_customer_uuid query param'
            return Response(msg, status=status.HTTP_400_BAD_REQUEST)
        return super().list(request)

    @property
    def base_queryset(self):
        """
        Required by the `PermissionRequiredForListingMixin`.
        For non-list actions, this is what's returned by `get_queryset()`.
        For list actions, some non-strict subset of this is what's returned by `get_queryset()`.

        Using the authenticated user's email address from the request:

        If enterprise_customer_uuid keyword argument is provided find all SubscriptionPlans with matching customer UUID.
        Return all Licenses that are associated with the user email and each of the customer's SubscriptionPlans.

        Otherwise, return an empty QuerySet.
        """
        if not self.enterprise_customer_uuid:
            return License.objects.none()

        user_email = self.request.user.email
        subscriptions = SubscriptionPlan.objects.filter(
            customer_agreement__enterprise_customer_uuid=self.enterprise_customer_uuid,
            is_active=True,
        )
        return License.objects.filter(
            subscription_plan__in=subscriptions,
            user_email=user_email,
        ).exclude(
            status=constants.REVOKED
        ).order_by('status', '-subscription_plan__expiration_date')


class PageNumberPaginationWithCount(PageNumberPagination):
    """
    A PageNumber paginator that adds the total number of pages to the paginated response.
    """
    def get_paginated_response(self, data):
        """ Adds a ``num_pages`` field into the paginated response. """
        response = super().get_paginated_response(data)
        response.data['num_pages'] = self.page.paginator.num_pages
        return response


class LicensePagination(PageNumberPaginationWithCount):
    """
    A PageNumber paginator that allows the client to specify the page size, up to some maximum.
    """
    page_size_query_param = 'page_size'
    max_page_size = 500


class LicenseViewSet(LearnerLicenseViewSet):
    """ Viewset for Admin read operations on Licenses."""
    lookup_field = 'uuid'
    lookup_url_kwarg = 'license_uuid'

    permission_required = constants.SUBSCRIPTIONS_ADMIN_ACCESS_PERMISSION
    allowed_roles = [constants.SUBSCRIPTIONS_ADMIN_ROLE]

    pagination_class = LicensePagination

    @property
    def base_queryset(self):
        """
        Required by the `PermissionRequiredForListingMixin`.
        For non-list actions, this is what's returned by `get_queryset()`.
        For list actions, some non-strict subset of this is what's returned by `get_queryset()`.
        """
        return License.objects.filter(subscription_plan=self._get_subscription_plan()).order_by('status', 'user_email')

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
        """
        Given a list of emails, assigns a license to those user emails and sends an activation email.

        This endpoint allows assigning licenses to users who have previously had a license revoked, by removing their
        association to the revoked licenses and then assigning them to unassigned licenses.
        """
        # Validate the user_emails and text sent in the data
        self._validate_data(request.data)
        # Dedupe all lowercase emails before turning back into a list for indexing
        user_emails = list({email.lower() for email in request.data.get('user_emails', [])})

        subscription_plan = self._get_subscription_plan()

        # Find any emails that have already been associated with a non-revoked license in the subscription
        # and remove from user_emails list
        already_associated_licenses = subscription_plan.licenses.filter(
            user_email__in=user_emails,
            status__in=[constants.ASSIGNED, constants.ACTIVATED],
        )
        if already_associated_licenses:
            already_associated_emails = list(already_associated_licenses.values_list('user_email', flat=True))
            for email in already_associated_emails:
                user_emails.remove(email.lower())

        # Get the revoked licenses that are attempting to be assigned to
        revoked_licenses_for_assignment = subscription_plan.licenses.filter(
            status=constants.REVOKED,
            user_email__in=user_emails,
        )

        # Make sure there are enough licenses that we can assign to
        num_user_emails = len(user_emails)
        num_unassigned_licenses = subscription_plan.unassigned_licenses.count()
        # Since we flip the status of revoked licenses when admins attempt to re-assign that learner to a new
        # license, we check that there are enough unassigned licenses when combined with the revoked licenses that
        # will have their status change
        num_potential_unassigned_licenses = num_unassigned_licenses + revoked_licenses_for_assignment.count()
        if num_user_emails > num_potential_unassigned_licenses:
            msg = (
                'There are not enough licenses that can be assigned to complete your request.'
                'You attempted to assign {} licenses, but there are only {} potentially available.'
            ).format(num_user_emails, num_potential_unassigned_licenses)
            return Response(msg, status=status.HTTP_400_BAD_REQUEST)

        # Flip all revoked licenses that were associated with emails that we are assigning to unassigned, and clear
        # all the old data on the license.
        for revoked_license in revoked_licenses_for_assignment:
            revoked_license.reset_to_unassigned()

        License.bulk_update(
            revoked_licenses_for_assignment,
            [
                'status',
                'user_email',
                'lms_user_id',
                'last_remind_date',
                'activation_date',
                'activation_key',
                'assigned_date',
                'revoked_date',
            ],
        )

        # Get a queryset of only the number of licenses we need to assign
        unassigned_licenses = subscription_plan.unassigned_licenses[:num_user_emails]
        for unassigned_license, email in zip(unassigned_licenses, user_emails):
            # Assign each email to a license and mark the license as assigned
            unassigned_license.user_email = email
            unassigned_license.status = constants.ASSIGNED
            activation_key = str(uuid4())
            unassigned_license.activation_key = activation_key
            unassigned_license.assigned_date = localized_utcnow()
            unassigned_license.last_remind_date = localized_utcnow()

        License.bulk_update(
            unassigned_licenses,
            ['user_email', 'status', 'activation_key', 'assigned_date', 'last_remind_date'],
        )

        # Create async chains of the pending learners and activation emails tasks with each batch of users
        # The task signatures are immutable, hence the `si()` - we don't want the result of the
        # link_learners_to_enterprise_task passed to the "child" activation_email_task.
        for pending_learner_batch in chunks(user_emails, constants.PENDING_ACCOUNT_CREATION_BATCH_SIZE):
            chain(
                link_learners_to_enterprise_task.si(
                    pending_learner_batch,
                    subscription_plan.enterprise_customer_uuid,
                ),
                activation_email_task.si(
                    self._get_custom_text(request.data),
                    pending_learner_batch,
                    subscription_uuid,
                )
            ).apply_async()

        # Pass email assignment data back to frontend for display
        response_data = {
            'num_successful_assignments': len(user_emails),
            'num_already_associated': len(already_associated_licenses)
        }
        return Response(data=response_data, status=status.HTTP_200_OK)

    @action(detail=False, methods=['post'])
    def remind(self, request, subscription_uuid=None):
        """
        Given a single email in the POST data, sends a reminder email that they have a license pending activation.

        This endpoint reminds users by sending an email to the given email address, if there is a license which has not
        yet been activated that is associated with that email address.
        """
        # Validate the user_email and text sent in the data
        self._validate_data(request.data)

        # Make sure there is a license that is still pending activation associated with the given email
        user_email = request.data.get('user_email')
        subscription_plan = self._get_subscription_plan()
        try:
            License.objects.get(
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

        return Response(status=status.HTTP_200_OK)

    @action(detail=False, methods=['post'])
    def revoke(self, request, subscription_uuid=None):  # pylint: disable=unused-argument
        self._validate_data(request.data)
        # Find the active or pending license for the user
        user_email = request.data.get('user_email')
        subscription_plan = self._get_subscription_plan()
        try:
            user_license = subscription_plan.licenses.get(
                user_email=user_email,
                status__in=[constants.ACTIVATED, constants.ASSIGNED]
            )
        except ObjectDoesNotExist:
            msg = 'Could not find any active licenses that are associated with the email: {}'.format(
                user_email,
            )
            return Response(msg, status=status.HTTP_404_NOT_FOUND)

        try:
            revoke_license(user_license)
        except LicenseRevocationError as exc:
            logger.error(exc)
            return Response(
                status=status.HTTP_400_BAD_REQUEST,
                data=exc.failure_reason,
            )

        return Response(status=status.HTTP_204_NO_CONTENT)

    @action(detail=False, methods=['get'])
    def overview(self, request, subscription_uuid=None):  # pylint: disable=unused-argument
        queryset = self.filter_queryset(self.get_queryset())
        queryset_values = queryset.values('status').annotate(count=Count('status')).order_by('-count')
        license_overview = list(queryset_values)
        return Response(license_overview, status=status.HTTP_200_OK)

    @action(detail=False, methods=['get'])
    def csv(self, request, subscription_uuid):  # pylint: disable=unused-argument
        """
        Returns license data for a given subscription in CSV format.

        Only includes licenses with a status of ACTIVATED, ASSIGNED, or REVOKED.
        """
        subscription = self._get_subscription_plan()
        enterprise_slug = subscription.customer_agreement.enterprise_customer_slug
        licenses = subscription.licenses.filter(
            status__in=[constants.ACTIVATED, constants.ASSIGNED, constants.REVOKED],
        ).values('status', 'user_email', 'activation_date', 'last_remind_date', 'activation_key')
        for lic in licenses:
            # We want to expose the full activation link rather than just the activation key
            lic['activation_link'] = get_license_activation_link(enterprise_slug, lic['activation_key'])
            lic.pop('activation_key', None)
        csv_data = CSVRenderer().render(list(licenses))
        return Response(csv_data, status=status.HTTP_200_OK, content_type='text/csv')


class LicenseBaseView(APIView):
    """
    Base view for creating specific, one-off views
    that deal with licenses.
    """
    permission_classes = [permissions.IsAuthenticated]

    @cached_property
    def decoded_jwt(self):
        return utils.get_decoded_jwt(self.request)

    @property
    def lms_user_id(self):
        return utils.get_key_from_jwt(self.decoded_jwt, 'user_id')

    @property
    def user_email(self):
        return utils.get_key_from_jwt(self.decoded_jwt, 'email')


class EnterpriseEnrollmentWithLicenseSubsidyView(LicenseBaseView):
    """
    View for validating a group of enterprise learners' license subsidies for a list of courses and then enrolling all
    provided learners in all courses.

    POST /api/v1/bulk-license-enrollment

    Required query param:
        - enterprise_customer_uuid (str): enterprise customer's uuid

    Required body params:
        - notify (bool): whether to notify the learners of their enrollment
        - course_run_keys (list): an array of string course run keys
        - emails (list): an array of learners' emails
    """
    validation_errors = None
    missing_params = None

    @property
    def requested_notify_learners(self):
        if not isinstance(self.request.data.get('notify'), bool):
            if self.request.data.get('notify'):
                self.validation_errors.append('notify')
        return self.request.data.get('notify')

    @property
    def requested_course_run_keys(self):
        if self.request.data.get('course_run_keys'):
            if not isinstance(self.request.data.get('course_run_keys'), list):
                self.validation_errors.append('course_run_keys')
        return self.request.data.get('course_run_keys')

    @property
    def requested_user_emails(self):
        if self.request.data.get('emails'):
            if not isinstance(self.request.data.get('emails'), list):
                self.validation_errors.append('emails')
        return self.request.data.get('emails')

    @property
    def requested_enterprise_id(self):
        return self.request.query_params.get('enterprise_customer_uuid')

    def _validate_request_params(self):
        """
        Helper function to validate both the existence of required params and their typing.
        """
        self.validation_errors = []
        self.missing_params = []
        if self.requested_notify_learners is None:
            self.missing_params.append('notify')

        # Gather all missing and incorrect typing validation errors
        if not self.requested_course_run_keys:
            self.missing_params.append('course_run_keys')
        if not self.requested_user_emails:
            self.missing_params.append('emails')
        if not self.requested_enterprise_id:
            self.missing_params.append('enterprise_customer_uuid')

        # Report param type errors
        if self.validation_errors:
            return 'Received invalid types for the following required params: {}'.format(self.validation_errors)

        # Report required params type errors
        if self.missing_params:
            return 'Missing the following required request data: {}'.format(self.missing_params)

        return ''

    def _check_missing_licenses(self, customer_agreement):
        """
        Helper function to check that each of the provided learners has a valid subscriptions license for the provided
        courses.
        """
        missing_subscriptions = {}
        licensed_enrollment_info = []

        for email in self.requested_user_emails:
            filtered_licenses = License.objects.filter(
                subscription_plan__in=customer_agreement.subscriptions.all(),
                user_email=email,
            )

            # order licenses by their associated subscription plan expiration date
            ordered_licenses_by_expiration = sorted(
                filtered_licenses,
                key=lambda user_license: user_license.subscription_plan.expiration_date,
                reverse=True,
            )
            for course_key in self.requested_course_run_keys:
                plan_found = False
                for user_license in ordered_licenses_by_expiration:
                    subscription_plan = user_license.subscription_plan
                    if subscription_plan.contains_content([course_key]):
                        licensed_enrollment_info.append({
                            'email': email,
                            'course_run_key': course_key,
                            'license_uuid': str(user_license.uuid)
                        })
                        plan_found = True
                if not plan_found:
                    if missing_subscriptions.get(email):
                        missing_subscriptions[email].append(course_key)
                    else:
                        missing_subscriptions[email] = [course_key]

        return missing_subscriptions, licensed_enrollment_info

    @permission_required(
        constants.SUBSCRIPTIONS_ADMIN_LEARNER_ACCESS_PERMISSION,
        fn=lambda request: utils.get_context_for_customer_agreement_from_request(request),  # pylint: disable=unnecessary-lambda
    )
    def post(self, request):
        """
        Returns the enterprise bulk enrollment API response after validating that each user requesting to be enrolled
        has a valid subscription for each of the requested courses.

        Expected params:
            - notify (bool): Whether or not learners should be notified of their enrollments.

            - course_run_keys (list of strings): An array of course run keys in which all provided learners will be
            enrolled in
            Example:
                course_run_keys: ['course-v1:edX+DemoX+Demo_Course', 'course-v2:edX+The+Second+DemoX+Demo_Course', ... ]

            - emails (string): A single string of multiple learner emails separated with a `\n` (new line) character
            Example:
                emails: 'testuser@abc.com\nlearner@example.com\newuser@wow.com'

            - enterprise_customer_uuid (string): the uuid of the associated enterprise customer provided as a query
            params.

        Expected Return Values:
            Success cases:
                - All learners have licenses and are enrolled - {}, 201

            Partial failure cases:
                License verification and bulk enterprise enrollment happen non-transactionally, meaning that a subset of
                learners failing one step will not stop others from continuing the enrollment flow. As such, partial
                failures will be reported in the following ways:

                Fails license verification:
                    response includes: {'failed_license_checks': [<users who do not have valid licenses>]}

                Fails Enrollment:
                    response includes {'failed_enrollments': [<users who were not able to be enrolled>]

                Fails Validation (something goes wrong with requesting enrollments):
                    response includes:
                     {'bulk_enrollment_errors': [<errors returned by the bulk enrollment endpoint>]}
        """
        param_validation = self._validate_request_params()
        if param_validation:
            return Response(param_validation, status=status.HTTP_400_BAD_REQUEST)

        results = {}
        customer_agreement = utils.get_customer_agreement_from_request_enterprise_uuid(request)
        missing_subscriptions, licensed_enrollment_info = self._check_missing_licenses(customer_agreement)

        if missing_subscriptions:
            msg = 'One or more of the learners entered do not have a valid subscription for your requested courses. ' \
                  'Learners: {}'.format(missing_subscriptions)
            results['failed_license_checks'] = missing_subscriptions
            logger.error(msg)

        if licensed_enrollment_info:
            options = {
                'licenses_info': licensed_enrollment_info,
                'notify': self.requested_notify_learners
            }
            enrollment_response = EnterpriseApiClient().bulk_enroll_enterprise_learners(
                self.requested_enterprise_id, options
            )

            # Check for bulk enrollment errors
            if enrollment_response.status_code >= 400 and enrollment_response.status_code != 409:
                status_code = status.HTTP_400_BAD_REQUEST
                results['bulk_enrollment_errors'] = []
                try:
                    response_json = enrollment_response.json()
                except JSONDecodeError:
                    # Catch uncaught exceptions from enterprise
                    results['bulk_enrollment_errors'].append(enrollment_response.reason)
                else:
                    msg = 'Encountered a validation error when requesting bulk enrollment. Endpoint returned with ' \
                          'error: {}'.format(response_json)
                    logger.error(msg)

                    # check for non field specific errors
                    if response_json.get('non_field_errors'):
                        results['bulk_enrollment_errors'].append(response_json['non_field_errors'])

                    # check for param field specific validation errors
                    for param in options:
                        if response_json.get(param):
                            results['bulk_enrollment_errors'].append(response_json.get(param))

            else:
                enrollment_result = enrollment_response.json()
                if enrollment_result.get('failures'):
                    results['failed_enrollments'] = enrollment_result['failures']

                if enrollment_result.get('failures') or missing_subscriptions:
                    status_code = status.HTTP_409_CONFLICT
                else:
                    status_code = status.HTTP_201_CREATED
        else:
            status_code = status.HTTP_404_NOT_FOUND

        return Response(results, status=status_code)


class LicenseSubsidyView(LicenseBaseView):
    """
    View for fetching the data on the subsidy provided by a license.
    """
    @property
    def requested_course_key(self):
        return self.request.query_params.get('course_key')

    @permission_required(
        constants.SUBSCRIPTIONS_ADMIN_LEARNER_ACCESS_PERMISSION,
        fn=lambda request: utils.get_context_for_customer_agreement_from_request(request),  # pylint: disable=unnecessary-lambda
    )
    def get(self, request):
        """
        Returns subsidy data for a course by a user's activated license from the given enterprise's active subscription.

        This method checks to see whether the given course is associated with their enterprise's active subscription by
        checking if the enterprise catalog associated with the subscription contains the specified course.
        The enterprise is specified by the `enterprise_customer_uuid` parameter, and the course key is specified by the
        `course_key` parameter.
        """
        if not self.requested_course_key:
            msg = 'You must supply the course_key query parameter'
            return Response(msg, status=status.HTTP_400_BAD_REQUEST)

        customer_agreement = utils.get_customer_agreement_from_request_enterprise_uuid(request)
        user_activated_licenses = License.objects.filter(
            subscription_plan__in=customer_agreement.subscriptions.all(),
            lms_user_id=self.lms_user_id,
            status=constants.ACTIVATED,
        )
        # order licenses by their associated subscription plan expiration date
        ordered_licenses_by_expiration = sorted(
            user_activated_licenses,
            key=lambda user_license: user_license.subscription_plan.expiration_date,
            reverse=True,
        )

        # iterate through the ordered licenses to return the license subsidy data for the user's license
        # which is "valid" for the specified content key and expires furthest in the future.
        for user_license in ordered_licenses_by_expiration:
            subscription_plan = user_license.subscription_plan
            course_in_catalog = subscription_plan.contains_content([self.requested_course_key])
            if not course_in_catalog:
                continue

            ordered_data = OrderedDict({
                'discount_type': constants.PERCENTAGE_DISCOUNT_TYPE,
                'discount_value': constants.LICENSE_DISCOUNT_VALUE,
                'status': user_license.status,
                'subsidy_id': user_license.uuid,
                'start_date': subscription_plan.start_date,
                'expiration_date': subscription_plan.expiration_date,
            })
            return Response(ordered_data)

        # user does not have an activated license that is applicable to the specified content key.
        msg = (
            'This course was not found in the subscription plan catalogs associated with the '
            'specified enterprise UUID.'
        )
        return Response(msg, status=status.HTTP_404_NOT_FOUND)


class LicenseActivationView(LicenseBaseView):
    """
    View for activating a license.  Assumes that the user is JWT-Authenticated.
    """

    @permission_required(
        constants.SUBSCRIPTIONS_ADMIN_LEARNER_ACCESS_PERMISSION,
        fn=lambda request: utils.get_context_from_subscription_plan_by_activation_key(request),  # pylint: disable=unnecessary-lambda
    )
    def post(self, request):
        """
        Activates a license, given an ``activation_key`` query param (which should be a UUID).

        Route: /api/v1/license-activation?activation_key=your-key

        Returns:
            * 400 Bad Request - if the ``activation_key`` query parameter is malformed or missing, or if
                the user's email could not be found in the jwt.
            * 401 Unauthorized - if the requesting user is not authenticated.
            * 403 Forbidden - if the requesting user is not allowed to access the associated
                 license's subscription plan.
            * 404 Not Found - if the email found in the request's JWT and the provided ``activation_key``
                 do not match those of any existing license in an activate subscription plan.
            * 204 No Content - if such a license was found, and if the license is currently ``assigned``,
                 it is updated with a status of ``activated``, its ``activation_date`` is set, and its ``lms_user_id``
                 is updated to the value found in the request's JWT.  If the license is already ``activated``,
                 no update is made to it.
            * 422 Unprocessable Entity - if we find a license, but it's status is not currently ``assigned``
                 or ``activated``, we do nothing and return a 422 with a message indicating that the license
                 cannot be activated.
        """
        activation_key_uuid = utils.get_activation_key_from_request(request)
        try:
            user_license = License.objects.get(
                activation_key=activation_key_uuid,
                user_email=self.user_email,
                subscription_plan__is_active=True,
            )
        except License.DoesNotExist:
            msg = 'No license exists for the email {} with activation key {}'.format(
                self.user_email,
                activation_key_uuid,
            )
            return Response(msg, status=status.HTTP_404_NOT_FOUND)

        if user_license.status not in (constants.ASSIGNED, constants.ACTIVATED):
            return Response(
                f'Cannot activate a license with a status of {user_license.status}',
                status=status.HTTP_422_UNPROCESSABLE_ENTITY,
            )

        if user_license.status == constants.ASSIGNED:
            user_license.status = constants.ACTIVATED
            user_license.activation_date = localized_utcnow()
            user_license.lms_user_id = self.lms_user_id
            user_license.save()

            # Following successful license activation, send learner an email
            # to help them get started using the Enterprise Learner Portal.
            send_onboarding_email_task.delay(
                user_license.subscription_plan.enterprise_customer_uuid,
                user_license.user_email,
            )

        return Response(status=status.HTTP_204_NO_CONTENT)


class UserRetirementView(APIView):
    """
    View for retiring users and their license data upon account deletion. Note that User data is deleted.
    """
    LMS_USER_ID = 'lms_user_id'
    ORIGINAL_USERNAME = 'original_username'

    authentication_classes = [JwtAuthentication]
    permission_classes = [permissions.IsAuthenticated, CanRetireUser]

    def _get_required_field(self, field_name):
        """
        Helper to get a required field from the POST data and return a 400 if it can't be found.
        """
        field_value = self.request.data.get(field_name)
        if not field_value:
            message = f'Required field "{field_name}" missing or missing value in retirement request"'
            logger.error('{}. Returning 400 BAD REQUEST'.format(message))
            raise ParseError(message)

        return field_value

    def post(self, request):
        """
        Retires a user and their associated licenses.

        Returns:
            * 400 Bad Request - if the `lms_user_id` or `original_username` data is missing from the POST request.
            * 401 Unauthorized - if the requesting user is not authenticated.
            * 403 Forbidden - if the requesting user does not have retirement permissions.
            * 404 Not Found - if no User object could be found with a username given by `original_username`. Note that
                associated licenses may still have been retired even if there was no associated User object. One
                instance where this can happen is if a user was assigned a license but never activated or used it.
            * 204 No Content - if the associated licenses and User object are wiped and deleted respectively.
        """
        lms_user_id = self._get_required_field(self.LMS_USER_ID)
        original_username = self._get_required_field(self.ORIGINAL_USERNAME)

        # Scrub all pii on licenses associated with the user
        associated_licenses = License.objects.filter(lms_user_id=lms_user_id)
        for associated_license in associated_licenses:
            # Scrub all pii on the revoked licenses, but they should stay revoked and keep their other info as we
            # currently add an unassigned license to the subscription's license pool whenever one is revoked.
            if associated_license.status == constants.REVOKED:
                associated_license.clear_pii()
            else:
                # For all other types of licenses, we can just reset them to unassigned (which clears all fields)
                associated_license.reset_to_unassigned()
            associated_license.save()
            # Clear historical pii after removing pii from the license itself
            associated_license.clear_historical_pii()
        associated_licenses_uuids = [license.uuid for license in associated_licenses]
        message = 'Retired {} licenses with uuids: {} for user with lms_user_id {}'.format(
            len(associated_licenses_uuids),
            sorted(associated_licenses_uuids),
            lms_user_id,
        )
        logger.info(message)

        try:
            User = get_user_model()
            user = User.objects.get(username=original_username)
            logger.info('Retiring user with id %r and lms_user_id %r', user.id, lms_user_id)
            user.delete()
        except ObjectDoesNotExist:
            return Response(status=status.HTTP_404_NOT_FOUND)
        except Exception as exc:  # pylint: disable=broad-except
            logger.exception('500 error retiring user with lms_user_id %r. Error: %s', lms_user_id, exc)
            return Response('Error retiring user', status=status.HTTP_500_INTERNAL_SERVER_ERROR)

        return Response(status=status.HTTP_204_NO_CONTENT)


class StaffLicenseLookupView(LicenseBaseView):
    """
    A class that allows users with staff permissions
    to lookup all licenses for a user, given the user's email address.

    POST /api/v1/staff_lookup_licenses
    With POST data

    {
        'user_email': 'someone@someplace.net'
    }

    Returns a response with status codes and data as follows:
        * 400 Bad Request - if the ``user_email`` data is missing from the POST request.
        * 401 Unauthorized - if the requesting user is not authenticated.
        * 403 Forbidden - if the requesting user does not have staff/administrator permissions.
        * 404 Not Found - if no licenses associated with the given email were found.
        * 200 OK - If at least one license associated with the given email was found.
                   The response data is a list of objects describing the license and associated subscription plan.

    Example response data:

    [
      {
        "status": "assigned",
        "assigned_date": "2020-12-31",
        "activation_date": null,
        "revoked_date": null,
        "last_remind_date": null,
        "subscription_plan_title": "Pied Piper's First Subscription - Renewed",
        "subscription_plan_expiration_date": "2022-11-30",
        "activation_link": "https://base.url/licenses/some-key/activate"
      }
    ]
    """
    authentication_classes = [JwtAuthentication]
    permission_classes = [permissions.IsAdminUser]

    def post(self, request):
        """
        For a given email address provided in POST data,
        returns all licenses and associated subscription data
        associated with that email address.
        """
        user_email = request.data.get('user_email')
        if not user_email:
            return Response(
                'A ``user_email`` is required in the request data',
                status=status.HTTP_400_BAD_REQUEST,
            )

        user_licenses = License.by_user_email(user_email)
        if not user_licenses:
            return Response(
                status=status.HTTP_404_NOT_FOUND,
            )

        serialized_licenses = serializers.StaffLicenseSerializer(user_licenses, many=True)

        return Response(
            serialized_licenses.data,
            status=status.HTTP_200_OK,
        )
