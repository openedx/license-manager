"""
Python APIs exposed by the Subscriptions app to other in-process apps.
"""
import logging

from django.db import transaction
from requests.exceptions import HTTPError

from license_manager.apps.api_client.enterprise import EnterpriseApiClient
from license_manager.apps.subscriptions import event_utils

from ..api.tasks import (
    revoke_course_enrollments_for_user_task,
    send_revocation_cap_notification_email_task,
)
from .constants import (
    ACTIVATED,
    ASSIGNED,
    UNASSIGNED,
    LicenseTypesToRenew,
    SegmentEvents,
)
from .exceptions import (
    CustomerAgreementError,
    LicenseRevocationError,
    RenewalProcessingError,
    UnprocessableSubscriptionPlanExpirationError,
    UnprocessableSubscriptionPlanFreezeError,
)
from .models import License, SubscriptionPlan
from .utils import localized_utcnow


logger = logging.getLogger(__name__)


def revoke_license(user_license):
    """
    Revoke a License.

    Arguments:
        user_license (License): The License to be revoked
    """
    # Number of revocations remaining can become negative if revoke max percentage is decreased
    is_revocation_cap_enabled = user_license.subscription_plan.is_revocation_cap_enabled
    revoke_limit_reached = not user_license.subscription_plan.has_revocations_remaining
    # Revocation of ASSIGNED licenses is not limited
    if revoke_limit_reached and user_license.status == ACTIVATED:
        raise LicenseRevocationError(
            user_license.uuid,
            "License revocation limit has been reached."
        )
    # Only allow revocation for ASSIGNED and ACTIVATED licenses
    if user_license.status not in [ACTIVATED, ASSIGNED]:
        raise LicenseRevocationError(
            user_license.uuid,
            "License with status of {license_status} cannot be revoked.".format(
                license_status=user_license.status
            )
        )

    if user_license.status == ACTIVATED:
        # We should only need to revoke enrollments if the License has an original
        # status of ACTIVATED, pending users shouldn't have any enrollments.
        revoke_course_enrollments_for_user_task.delay(
            user_id=user_license.lms_user_id,
            enterprise_id=str(user_license.subscription_plan.enterprise_customer_uuid),
        )
        if is_revocation_cap_enabled:
            # Revocation only counts against the limit for ACTIVATED licenses
            user_license.subscription_plan.num_revocations_applied += 1
            user_license.subscription_plan.save()

    if not user_license.subscription_plan.has_revocations_remaining:
        # Send email notification to ECS that the Subscription Plan has reached its revocation cap
        send_revocation_cap_notification_email_task.delay(
            subscription_uuid=user_license.subscription_plan.uuid,
        )

    # Revoke the license
    user_license.revoke()
    logger.info('License {} has been revoked'.format(user_license.uuid))
    # Create new license to add to the unassigned license pool
    user_license.subscription_plan.increase_num_licenses(1)


def renew_subscription(subscription_plan_renewal, is_auto_renewed=False):
    """
    Renew the subscription plan.
    """
    original_plan = subscription_plan_renewal.prior_subscription_plan
    original_licenses = _original_licenses_to_copy(
        original_plan,
        subscription_plan_renewal.license_types_to_copy,
    )

    if subscription_plan_renewal.number_of_licenses < len(original_licenses):
        raise RenewalProcessingError("Cannot renew for fewer than the number of original activated licenses.")

    future_plan = subscription_plan_renewal.renewed_subscription_plan
    if not future_plan:
        # create the renewed plan
        future_plan = SubscriptionPlan(
            title=subscription_plan_renewal.get_renewed_plan_title(),
            start_date=subscription_plan_renewal.effective_date,
            expiration_date=subscription_plan_renewal.renewed_expiration_date,
            enterprise_catalog_uuid=original_plan.enterprise_catalog_uuid,
            customer_agreement=original_plan.customer_agreement,
            is_active=original_plan.is_active,
            netsuite_product_id=original_plan.netsuite_product_id,
            salesforce_opportunity_id=subscription_plan_renewal.salesforce_opportunity_id,
            plan_type_id=subscription_plan_renewal.prior_subscription_plan.plan_type_id,
            is_revocation_cap_enabled=subscription_plan_renewal.prior_subscription_plan.is_revocation_cap_enabled,
            revoke_max_percentage=subscription_plan_renewal.prior_subscription_plan.revoke_max_percentage,
            for_internal_use_only=subscription_plan_renewal.prior_subscription_plan.for_internal_use_only,
        )

    # When creating SubscriptionPlans in Django admin, we create enough
    # Licenses associated with it to satisfy the "num_licenses" form field.
    # If a user enters a non-zero number in this field while setting up a new
    # SubscriptionPlanRenewal (i.e. so that there's an existant plan to renew
    # into), we'll have to modify existing Licenses in the renewed plan.
    licenses_for_renewal = list(future_plan.licenses.all())

    # Are there any licenses in the renewed plan that aren't UNASSIGNED?
    # because there shouldn't be
    if any(_license.status != UNASSIGNED for _license in licenses_for_renewal):
        raise RenewalProcessingError(
            "Renewal can't be processed; there are existing licenses "
            "in the renewed plan that are activated/assigned/revoked."
        )

    if len(licenses_for_renewal) > subscription_plan_renewal.number_of_licenses:
        raise RenewalProcessingError("More licenses exist than were requested to be renewed.")

    with transaction.atomic():
        future_plan.save()
        future_plan.increase_num_licenses(
            subscription_plan_renewal.number_of_licenses - future_plan.num_licenses
        )

        _renew_all_licenses(
            original_licenses,
            future_plan,
            is_auto_renewed
        )

        subscription_plan_renewal.renewed_subscription_plan = future_plan
        subscription_plan_renewal.processed = True
        subscription_plan_renewal.processed_datetime = localized_utcnow()
        subscription_plan_renewal.save()


def _renew_all_licenses(original_licenses, future_plan, is_auto_renewed):
    """
    We assume at this point that the future plan has at least as many licenses
    as the number of licenses in the original plan.  Does a bulk update of
    the renewed licenses.
    """
    future_licenses = []

    for original_license, future_license in zip(original_licenses, future_plan.licenses.all()):
        future_license.status = original_license.status
        future_license.user_email = original_license.user_email
        future_license.lms_user_id = original_license.lms_user_id
        future_license.activation_key = original_license.activation_key
        future_license.assigned_date = localized_utcnow()
        if original_license.status == ACTIVATED:
            future_license.activation_date = future_plan.start_date

        future_licenses.append(future_license)

        original_license.renewed_to = future_license
    License.bulk_update(
        future_licenses,
        ['status', 'user_email', 'lms_user_id', 'activation_date', 'assigned_date'],
    )
    License.bulk_update(
        original_licenses,
        ['renewed_to'],
    )

    for future_license in future_licenses:
        event_properties = event_utils.get_license_tracking_properties(future_license)
        event_properties['is_auto_renewed'] = is_auto_renewed
        event_utils.track_event(future_license.lms_user_id,
                                SegmentEvents.LICENSE_RENEWED,
                                event_properties)


def _original_licenses_to_copy(original_plan, license_types_to_copy):
    """
    Returns a list of licenses to copy from an original plan to
    a future plan as part of the renewal process.
    """
    if license_types_to_copy == LicenseTypesToRenew.NOTHING:
        return[]

    if license_types_to_copy == LicenseTypesToRenew.ASSIGNED_AND_ACTIVATED:
        license_status_kwargs = {'status__in': (ASSIGNED, ACTIVATED)}
    elif license_types_to_copy == LicenseTypesToRenew.ACTIVATED:
        license_status_kwargs = {'status': ACTIVATED}

    return list(original_plan.licenses.filter(**license_status_kwargs))


def expire_plan_post_renewal(subscription_plan):
    """
    Expires an old plan and marks its associated licenses
    as transferred.

    The original license can't be marked as transferred until after the original
    plan expires.  So we'll need a management command to periodically look
    through expired plans, see if they were renewed, and update the
    status of the expired plan's (previously) active licenses.
    """
    if subscription_plan.expiration_processed:
        raise UnprocessableSubscriptionPlanExpirationError(
            "Cannot expire {}. The plan's expiration is already marked as processed.".format(subscription_plan)
        )

    if subscription_plan.expiration_date > localized_utcnow():
        raise UnprocessableSubscriptionPlanExpirationError(
            "Cannot expire {}. The plan's expiration date is in the future.".format(subscription_plan)
        )

    renewal = subscription_plan.get_renewal()
    if not renewal:
        raise UnprocessableSubscriptionPlanExpirationError(
            "Cannot expire {}. The plan has no associated renewal record.".format(subscription_plan)
        )

    if not renewal.processed:
        raise UnprocessableSubscriptionPlanExpirationError(
            "Cannot expire {}. The plan's renewal has not been processed.".format(subscription_plan)
        )

    subscription_plan.expiration_processed = True
    subscription_plan.save(update_fields=['expiration_processed'])


def delete_unused_licenses_post_freeze(subscription_plan):
    """
    Processes a "freeze" request on a SubscriptionPlan. Any unassigned licenses will be deleted, but
    licenses in other states (e.g., activated, assigned, revoked) will persist.

    The ability for a Subscription Plan to be "frozen" relies on a configurable toggle.
    """
    if not subscription_plan.can_freeze_unused_licenses:
        raise UnprocessableSubscriptionPlanFreezeError(
            f"Cannot freeze {subscription_plan}. The plan does not support freezing unused licenses."
        )
    subscription_plan.unassigned_licenses.delete()
    subscription_plan.last_freeze_timestamp = localized_utcnow()
    subscription_plan.save()


def sync_agreement_with_enterprise_slug(customer_agreement):
    """
    Syncs any updates made to the enterprise customer slug as returned by the ``EnterpriseApiClient``
    with the specified ``CustomerAgreement``.
    """
    try:
        customer_data = EnterpriseApiClient().get_enterprise_customer_data(
            customer_agreement.enterprise_customer_uuid,
        )
        customer_agreement.enterprise_customer_slug = customer_data.get('slug')
        customer_agreement.save()
    except HTTPError as exc:
        error_message = (
            'Could not fetch customer slug field from the enterprise API: {}'.format(exc)
        )
        raise CustomerAgreementError(error_message) from exc
