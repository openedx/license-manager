from django.core.validators import MinLengthValidator
from rest_framework import serializers
from rest_framework.fields import SerializerMethodField
from django.conf import settings

from license_manager.apps.subscriptions.constants import (
    ACTIVATED,
    ASSIGNED,
    REVOKED,
    SALESFORCE_ID_LENGTH,
    MAX_NUM_LICENSES
)
from license_manager.apps.subscriptions.utils import (
    verify_sf_opportunity_product_line_item,
    validate_enterprise_catalog_uuid
)

from license_manager.apps.subscriptions.exceptions import (
    InvalidSubscriptionPlanPayloadError
)
from license_manager.apps.subscriptions.models import (
    CustomerAgreement,
    License,
    SubscriptionPlan,
    SubscriptionPlanRenewal,
)


class SubscriptionPlanRenewalSerializer(serializers.ModelSerializer):
    """
    Serializer for the `SubscriptionPlanRenewal` model.
    """

    prior_subscription_plan_start_date = serializers.UUIDField(source='prior_subscription_plan.start_date')
    renewed_subscription_plan_start_date = serializers.UUIDField(source='renewed_subscription_plan.start_date')

    class Meta:
        model = SubscriptionPlanRenewal
        fields = [
            'prior_subscription_plan_id',
            'prior_subscription_plan_start_date',
            'renewed_subscription_plan_id',
            'renewed_subscription_plan_start_date',
        ]


class MinimalSubscriptionPlanSerializer(serializers.ModelSerializer):
    """
    Minimal serializer for the `SubscriptionPlan` model.
    """

    class Meta:
        model = SubscriptionPlan
        fields = [
            'title',
            'uuid',
            'start_date',
            'expiration_date',
            'enterprise_customer_uuid',
            'enterprise_catalog_uuid',
            'is_active',
            'is_revocation_cap_enabled',
            'days_until_expiration',
            'days_until_expiration_including_renewals',
            'is_locked_for_renewal_processing',
            'should_auto_apply_licenses'
        ]


class SubscriptionPlanSerializer(MinimalSubscriptionPlanSerializer):
    """
    Enhanced serializer for the `SubscriptionPlan` model.
    """
    licenses = serializers.SerializerMethodField()
    revocations = serializers.SerializerMethodField()
    prior_renewals = SubscriptionPlanRenewalSerializer(many=True)

    class Meta:
        model = SubscriptionPlan
        fields = MinimalSubscriptionPlanSerializer.Meta.fields + [
            'licenses',
            'revocations',
            'prior_renewals',
        ]

    def get_licenses(self, obj):
        """
        Returns the number of licenses that are currently
        associated with the plan (obj), assigned or activated in the plan,
        or revoked in the plan.

        Returns a dictionary with keys 'activated', 'allocated', 'assigned',
        'revoked', 'total', and 'unassigned'.  Note that 'total' does not include
        revoked licenses in its count - see the docstring of `num_licenses()` for
        more details.
        """
        count_by_status = obj.license_count_by_status()

        total_count = 0
        for status, count_for_status in count_by_status.items():
            if status != REVOKED:
                total_count += count_for_status

        count_by_status['total'] = total_count
        count_by_status['allocated'] = count_by_status[ASSIGNED] + count_by_status[ACTIVATED]
        return count_by_status

    def get_revocations(self, obj):
        """
        If the revocation cap is enabled for the plan (obj),
        returns a count of the number of revocations ever applied
        and how many are remaining before the cap is reached.

        If the revocation cap is not enabled for the plan, returns null.
        """
        if not obj.is_revocation_cap_enabled:
            return None

        return {
            'applied': obj.num_revocations_applied,
            'remaining': obj.num_revocations_remaining,
        }


class SubscriptionPlanCreateSerializer(SubscriptionPlanSerializer):
    """
    Serializer for SubscriptionPlan model to validate and create new records via API.

    Raises:
        InvalidSubscriptionPlanPayloadError: message
    """
    prior_renewals = None
    enterprise_catalog_uuid = serializers.UUIDField(
        required=False, allow_null=True)
    desired_num_licenses = serializers.IntegerField(required=True)
    customer_agreement = serializers.UUIDField(required=True)

    is_revocation_cap_enabled = serializers.BooleanField(
        required=False, default=False)
    revoke_max_percentage = serializers.IntegerField(required=False, default=5)
    change_reason = serializers.CharField(write_only=True)
    salesforce_opportunity_line_item = serializers.CharField(required=True)

    class Meta:
        model = SubscriptionPlan
        fields = MinimalSubscriptionPlanSerializer.Meta.fields + [
            'can_freeze_unused_licenses',
            'customer_agreement',
            'desired_num_licenses',
            'expiration_processed',
            'for_internal_use_only',
            'last_freeze_timestamp',
            'num_revocations_applied',
            'product',
            'revoke_max_percentage',
            'salesforce_opportunity_line_item',
            'is_revocation_cap_enabled',
            'change_reason',
        ]

    def create(self, validated_data):
        change_reason = validated_data.pop('change_reason')
        instance = SubscriptionPlan.objects.create(**validated_data)
        instance._change_reason = change_reason
        instance.save()
        return instance

    def validate(self, attrs):
        enterprise_catalog_uuid = attrs.get('enterprise_catalog_uuid')
        customer_agreement_uuid = attrs.get("customer_agreement")
        product = attrs.get('product')
        if not product:
            raise InvalidSubscriptionPlanPayloadError('Product is required.')

        customer_agreement = CustomerAgreement.objects.none()
        try:
            customer_agreement = CustomerAgreement.objects.get(
                pk=customer_agreement_uuid)
            attrs['customer_agreement'] = customer_agreement
        except Exception as ex:  # pylint: disable=broad-except
            raise InvalidSubscriptionPlanPayloadError(
                'Invalid customer_agreement.') from ex

        if not enterprise_catalog_uuid:
            attrs['enterprise_catalog_uuid'] = str(
                customer_agreement.default_enterprise_catalog_uuid)

        if 'customer_agreement' in attrs:
            if not customer_agreement.default_enterprise_catalog_uuid and not enterprise_catalog_uuid:
                raise InvalidSubscriptionPlanPayloadError(
                    'The subscription must have an enterprise catalog uuid from itself or its customer agreement',
                )

        licenses = attrs.get('num_licenses', 0)
        # Only internal use subscription plans to have more than the maximum number of licenses
        if licenses > MAX_NUM_LICENSES and not attrs.get('for_internal_use_only'):
            raise InvalidSubscriptionPlanPayloadError(
                f'Non-test subscriptions may not have more than {MAX_NUM_LICENSES} licenses',
            )

        # Ensure the revoke max percentage is between 0 and 100
        if attrs.get('is_revocation_cap_enabled') and attrs.get('revoke_max_percentage') > 100:
            raise InvalidSubscriptionPlanPayloadError(
                'Must be a valid percentage (0-100).')

        if (
                product.plan_type.sf_id_required
                and attrs.get('salesforce_opportunity_line_item') is None
                or not verify_sf_opportunity_product_line_item(attrs.get(
                'salesforce_opportunity_line_item'))
        ):
            raise InvalidSubscriptionPlanPayloadError(
                'You must specify Salesforce ID for selected product. It must start with \'00k\'.',
            )
        if settings.VALIDATE_FORM_EXTERNAL_FIELDS and attrs.get('enterprise_catalog_uuid') and \
                not validate_enterprise_catalog_uuid(
                    enterprise_catalog_uuid=attrs.get(
                        'enterprise_catalog_uuid'),
                    enterprise_customer_uuid=customer_agreement.enterprise_customer_uuid,
        ):
            raise InvalidSubscriptionPlanPayloadError(
                'bad catalog uuid validation')
        return attrs

    def to_representation(self, instance):
        data = super().to_representation(instance)
        data['uuid'] = instance.uuid
        data['change_reason'] = instance._change_reason  # pylint: disable=protected-access
        data['uuid'] = instance.uuid
        data['days_until_expiration_including_renewals'] = instance.days_until_expiration_including_renewals
        data['days_until_expiration'] = instance.days_until_expiration
        data['enterprise_customer_uuid'] = instance.enterprise_customer_uuid
        data['is_locked_for_renewal_processing'] = instance.is_locked_for_renewal_processing
        data['customer_agreement'] = instance.customer_agreement.uuid
        return data


class SubscriptionPlanUpdateSerializer(SubscriptionPlanCreateSerializer):
    """
    Serializer for SubscriptionPlan model to validate and update existing records via API.

    Raises:
        InvalidSubscriptionPlanPayloadError: message
    """

    enterprise_catalog_uuid = serializers.CharField(required=False)
    customer_agreement = serializers.ReadOnlyField()
    desired_num_licenses = serializers.ReadOnlyField()
    expiration_processed = serializers.ReadOnlyField()
    last_freeze_timestamp = serializers.ReadOnlyField()
    num_revocations_applied = serializers.ReadOnlyField()

    class Meta:
        model = SubscriptionPlan
        fields = [
            'can_freeze_unused_licenses',
            'change_reason',
            'enterprise_catalog_uuid',
            'expiration_date',
            'for_internal_use_only',
            'is_active',
            'is_revocation_cap_enabled',
            'product',
            'revoke_max_percentage',
            'salesforce_opportunity_line_item',
            'should_auto_apply_licenses',
            'start_date',
            'title',
            'customer_agreement',
            'desired_num_licenses',
            'expiration_processed',
            'last_freeze_timestamp',
            'num_revocations_applied',
        ]

    def validate(self, attrs):
        # Ensure the revoke max percentage is between 0 and 100
        if attrs.get('is_revocation_cap_enabled') and attrs.get('revoke_max_percentage') > 100:
            raise InvalidSubscriptionPlanPayloadError(
                'Must be a valid percentage (0-100).')
        subscription = self.context.get('subscription')
        product = attrs.get('product')
        if product:
            if (
                product.plan_type.sf_id_required
                and attrs.get('salesforce_opportunity_line_item') is None
                or not verify_sf_opportunity_product_line_item(attrs.get(
                    'salesforce_opportunity_line_item'))
            ):
                raise InvalidSubscriptionPlanPayloadError(
                    'You must specify Salesforce ID for selected product. It must start with \'00k\'.',
                )
        if settings.VALIDATE_FORM_EXTERNAL_FIELDS and attrs.get('enterprise_catalog_uuid') and \
                not validate_enterprise_catalog_uuid(
                    enterprise_catalog_uuid=attrs.get(
                        'enterprise_catalog_uuid'),
                    enterprise_customer_uuid=subscription.customer_agreement.enterprise_customer_uuid,
        ):
            raise InvalidSubscriptionPlanPayloadError('bad catalog uuid validation')

        return attrs


class MinimalCustomerAgreementSerializer(serializers.ModelSerializer):
    """
    Minimal serializer for the `CustomerAgreement` model. Does not
    include a nested representation of related subscription plans.
    """

    subscription_for_auto_applied_licenses = serializers.SerializerMethodField()

    class Meta:
        model = CustomerAgreement
        fields = [
            'uuid',
            'enterprise_customer_uuid',
            'enterprise_customer_slug',
            'default_enterprise_catalog_uuid',
            'disable_expiration_notifications',
            'net_days_until_expiration',
            'subscription_for_auto_applied_licenses',
            'available_subscription_catalogs',
        ]

    def get_subscription_for_auto_applied_licenses(self, obj):
        subscription_plan = obj.auto_applicable_subscription
        return subscription_plan.uuid if subscription_plan else None


class CustomerAgreementSerializer(MinimalCustomerAgreementSerializer):
    """
    Expanded serializer for the `CustomerAgreement` model.
    """
    subscriptions = SerializerMethodField()

    class Meta:
        model = CustomerAgreement
        fields = MinimalCustomerAgreementSerializer.Meta.fields + [
            'subscriptions',
        ]

    @property
    def serialize_active_plans_only(self):
        return self.context.get('active_plans_only', True)

    def get_subscriptions(self, obj):
        """
        Returns a serialized dictionary of all or active-only plans in this agreement.
        """
        plans = obj.subscriptions.all()

        if self.serialize_active_plans_only:
            plans = [plan for plan in plans if plan.is_active]

        serializer = SubscriptionPlanSerializer(plans, many=True)
        return serializer.data


class LicenseSerializer(serializers.ModelSerializer):
    """
    Serializer for the `License` model.
    """

    subscription_plan_uuid = serializers.UUIDField(source='subscription_plan_id')

    class Meta:
        model = License
        fields = [
            'uuid',
            'status',
            'user_email',
            'activation_date',
            'last_remind_date',
            'subscription_plan_uuid',
            'revoked_date',
            'activation_key',
        ]


class LearnerLicenseSerializer(LicenseSerializer):
    """
    Serializes licenses for consumption by the "owning" users.
    Includes nested serialization of the related customer agreement,
    and by extension, the subscription plans related to that customer agreement.
    """
    customer_agreement = MinimalCustomerAgreementSerializer(source='subscription_plan.customer_agreement')
    subscription_plan = MinimalSubscriptionPlanSerializer()

    class Meta:
        model = License
        fields = LicenseSerializer.Meta.fields + [
            'customer_agreement',
            'subscription_plan',
        ]


class StaffLicenseSerializer(serializers.ModelSerializer):
    """
    Serializer for the ``License`` model that is usable by views
    that are restricted to staff/admin users.
    """

    subscription_plan_title = serializers.CharField(source='subscription_plan.title')
    subscription_plan_expiration_date = serializers.DateTimeField(source='subscription_plan.expiration_date')

    class Meta:
        model = License
        fields = [
            'status',
            'assigned_date',
            'activation_date',
            'revoked_date',
            'last_remind_date',
            'subscription_plan_title',
            'subscription_plan_expiration_date',
            'activation_link',
        ]


# Action Serializers
class SingleEmailSerializer(serializers.Serializer):  # pylint: disable=abstract-method
    """
    Serializer for specifying a single email

    Requires that a valid, non-empty email is submitted.
    """
    user_email = serializers.EmailField(
        allow_blank=False,
        required=True,
        write_only=True,
    )

    class Meta:
        fields = [
            'user_email',
        ]


class MultipleEmailsSerializer(serializers.Serializer):  # pylint: disable=abstract-method
    """
    Serializer for specifying multiple emails

    Requires that a list of valid, non-empty emails are submitted.
    """
    user_emails = serializers.ListField(
        child=serializers.EmailField(
            allow_blank=False,
            write_only=True,
        ),
        allow_empty=False,
    )

    class Meta:
        fields = [
            'user_emails',
        ]


class CustomTextSerializer(serializers.Serializer):  # pylint: disable=abstract-method
    """
    Serializer for specifying custom text to use in license management emails.
    """
    greeting = serializers.CharField(
        allow_blank=True,
        required=False,
        write_only=True,
    )
    closing = serializers.CharField(
        allow_blank=True,
        required=False,
        write_only=True,
    )

    class Meta:
        fields = [
            'greeting',
            'closing',
        ]


class CustomTextWithMultipleEmailsSerializer(MultipleEmailsSerializer, CustomTextSerializer):  # pylint: disable=abstract-method
    """
    Serializer for specifying custom text to use in a license management email for multiple user_emails
    """
    class Meta:
        fields = MultipleEmailsSerializer.Meta.fields + CustomTextSerializer.Meta.fields


class MultipleOrSingleEmailSerializer(serializers.Serializer):  # pylint: disable=abstract-method
    """
    Serializer for specifying multiple or single email

    Requires that valid emails are submitted.
    """
    user_email = serializers.EmailField(
        allow_blank=True,
        required=False,
        write_only=True,
    )

    user_emails = serializers.ListField(
        child=serializers.EmailField(
            allow_blank=True,
            write_only=True,
        ),
        allow_empty=True,
        required=False,
    )

    class Meta:
        fields = [
            'user_email',
            'user_emails',
        ]


class CustomTextWithMultipleOrSingleEmailSerializer(MultipleOrSingleEmailSerializer, CustomTextSerializer):  # pylint: disable=abstract-method
    """
    Serializer for specifying custom text to use in a license management email for
    either multiple user_emails or a single email.
    """
    class Meta:
        fields = MultipleOrSingleEmailSerializer.Meta.fields + CustomTextSerializer.Meta.fields


class LicenseAdminBulkActionSerializer(serializers.Serializer):  # pylint: disable=abstract-method
    """
    Serializer for license admin bulk actions.

    Takes either a list of user_emails or a list of filters, but not both.
    """

    user_emails = serializers.ListField(
        child=serializers.EmailField(
            allow_blank=False,
            write_only=True,
        ),
        allow_empty=False,
        required=False,
    )

    filters = serializers.ListField(
        child=serializers.DictField(),
        allow_empty=False,
        required=False
    )

    class Meta:
        fields = ['user_emails', 'filters']

    def _validate_filters(self, filters):
        """
        Validate filters that were passed in. Only user_email and status filters are supported.
        """

        if not filters:
            return

        supported_filters = ['user_email', 'status_in']

        for fltr in filters:
            filter_name = fltr.get('name')
            filter_value = fltr.get('filter_value')

            if filter_name not in supported_filters:
                raise serializers.ValidationError(f'Malformed filters, supported filters are {supported_filters}.')

            if filter_name == 'user_email' and not isinstance(filter_value, str):
                raise serializers.ValidationError('Malformed filters, user_email must be a string.')

            if filter_name == 'status_in' and not isinstance(filter_value, list) \
                    and not all(isinstance(s, str) for s in filter_value):
                raise serializers.ValidationError('Malformed filters, status_in must be a list of strings.')

    def validate(self, attrs):
        user_emails = attrs.get('user_emails')
        filters = attrs.get('filters')

        if not (user_emails or filters):
            raise serializers.ValidationError('Either user_emails or filters must be provided.')

        if user_emails and filters:
            raise serializers.ValidationError('Either user_emails or filters must be provided, but not both.')

        self._validate_filters(filters)
        return super().validate(attrs)


class LicenseAdminRemindActionSerializer(  # pylint: disable=abstract-method
    LicenseAdminBulkActionSerializer,
    CustomTextSerializer
):
    """
    Serializer for the license admin remind action.
    """

    class Meta:
        fields = LicenseAdminBulkActionSerializer.Meta.fields + CustomTextSerializer.Meta.fields


class LicenseAdminAssignActionSerializer(CustomTextWithMultipleEmailsSerializer):  # pylint: disable=abstract-method
    """
    Serializer for the license admin assign action.
    """

    notify_users = serializers.BooleanField(required=False)
    user_sfids = serializers.ListField(
        child=serializers.CharField(
            allow_blank=True,
            allow_null=True,
            write_only=True,
            validators=[MinLengthValidator(SALESFORCE_ID_LENGTH)]
        ),
        allow_empty=False,
        required=False,
        error_messages={"empty": "No Salesforce Ids provided."}
    )

    class Meta:
        fields = CustomTextWithMultipleEmailsSerializer.Meta.fields + [
            'notify_users',
        ]

    def validate(self, attrs):
        user_emails = attrs.get('user_emails')
        user_sfids = attrs.get('user_sfids')

        if user_sfids:
            # if saleforce ids list is present then its length must be equal to number of user emails
            if len(user_emails) != len(user_sfids):
                raise serializers.ValidationError(
                    'Number of Salesforce IDs did not match number of provided user emails.'
                )

        return super().validate(attrs)


class EnterpriseEnrollmentWithLicenseSubsidyQueryParamsSerializer(serializers.Serializer):  # pylint: disable=abstract-method
    """
    Serializer for the enterprise enrollment with license subsidy query params
    """

    enterprise_customer_uuid = serializers.UUIDField(
        required=True,
        help_text='The UUID of the associated enterprise customer',
    )
    enroll_all = serializers.BooleanField(
        required=False,
        help_text='A boolean indicating whether to enroll all learners or not',
    )
    subscription_uuid = serializers.UUIDField(
        required=False,
        help_text='The UUID of the subscription',
    )

    class Meta:
        fields = [
            'enterprise_customer_uuid',
            'enroll_all',
            'subscription_uuid',
        ]


class EnterpriseEnrollmentWithLicenseSubsidyRequestSerializer(serializers.Serializer):  # pylint: disable=abstract-method
    """
    Serializer for the enterprise enrollment with license subsidy request
    """

    emails = serializers.ListField(
        child=serializers.EmailField(
            allow_blank=False,
        ),
        allow_empty=False,
        required=True,
        help_text='an array of learners\' emails',
    )
    course_run_keys = serializers.ListField(
        child=serializers.CharField(
            allow_blank=False,
            write_only=True,
        ),
        allow_empty=False,
        required=True,
        help_text='an array of course run keys',
    )
    notify = serializers.BooleanField(
        required=True,
        help_text='a boolean indicating whether to notify learners or not',
    )

    class Meta:
        fields = [
            'emails',
            'course_run_keys',
            'notify',
        ]


class SubscriptionPlanQueryParamsSerializer(serializers.Serializer):  # pylint: disable=abstract-method
    """
    Serializer for the subscription plan query params
    """

    enterprise_customer_uuid = serializers.UUIDField(
        required=False,
        help_text='The UUID of the associated enterprise customer',
    )

    class Meta:
        fields = [
            'enterprise_customer_uuid',
        ]
