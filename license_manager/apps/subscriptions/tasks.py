"""
Celery tasks for the subscriptions app.
"""
import functools
import logging

from celery import shared_task
from celery_utils.logged_task import LoggedTask
from django.db import IntegrityError
from django.db.utils import OperationalError

from license_manager.apps.api.utils import (
    acquire_subscription_plan_lock,
    release_subscription_plan_lock,
)
from license_manager.apps.subscriptions.models import SubscriptionPlan
from license_manager.apps.subscriptions.utils import batch_counts


logger = logging.getLogger(__name__)

TASK_RETRY_SECONDS = 60
PROVISION_LICENSES_BATCH_SIZE = 300

# 200 minutes will get you about 2 million licenses, give or take.
PROVISION_LICENSES_TIME_LIMIT_SECONDS = 60 * 200


class RequiredTaskUnreadyError(Exception):
    """
    An exception representing a state where one type of task that is required
    to be complete before another task is run is not in a ready state.
    """


def subscription_plan_semaphore():
    """
    Celery Task decorator that wraps a bound (bind=True) task.  If another wrapped task with the same given
    "subscription_plan_uuid" kwarg value is still running, defer running this task (by retrying until all other tasks
    are completed).
    """
    def decorator(task):
        @functools.wraps(task)
        def wrapped_task(self, *args, **kwargs):
            subscription_plan = SubscriptionPlan.objects.get(uuid=kwargs['subscription_plan_uuid'])
            if not acquire_subscription_plan_lock(subscription_plan):
                logger.info(
                    f'Deferring task {self.name} with id {self.request.id} '
                    f'and args: {self.request.args}, kwargs: {self.request.kwargs}, '
                    'since another task run with the same subscription plan has not yet completed.'
                )
                raise self.retry(exc=RequiredTaskUnreadyError())
            # Try to run the task.  If it fails, release the lock and bubble up the exception.
            try:
                task_results = task(self, *args, **kwargs)
            finally:
                release_subscription_plan_lock(subscription_plan)
            return task_results
        return wrapped_task
    return decorator


class LoggedTaskWithRetry(LoggedTask):  # pylint: disable=abstract-method
    """
    Shared base task that allows tasks that raise some common exceptions to retry automatically.

    See https://docs.celeryproject.org/en/stable/userguide/tasks.html#automatic-retry-for-known-exceptions for
    more documentation.
    """
    autoretry_for = (
        IntegrityError,
        OperationalError,
    )
    retry_kwargs = {'max_retries': 5}
    # Use exponential backoff for retrying tasks
    retry_backoff = True
    # Add randomness to backoff delays to prevent all tasks in queue from executing simultaneously
    retry_jitter = True


@shared_task(
    base=LoggedTaskWithRetry,
    bind=True,
    default_retry_delay=TASK_RETRY_SECONDS,
    soft_time_limit=PROVISION_LICENSES_TIME_LIMIT_SECONDS,
    time_limit=PROVISION_LICENSES_TIME_LIMIT_SECONDS,
)
@subscription_plan_semaphore()
def provision_licenses_task(self, subscription_plan_uuid=None):  # pylint: disable=unused-argument
    """
    For a given subscription plan, try to make its count of licenses match the number defined by the
    `desired_num_licenses` field of that subscription plan.  Never decrease the count of licenses; if there are already
    more licenses than `desired_num_licenses`, do nothing.

    Args:
        subscription_plan_uuid (str): UUID of the SubscriptionPlan object to provision licenses for.
    """
    subscription_plan = SubscriptionPlan.objects.get(uuid=subscription_plan_uuid)
    if not subscription_plan.desired_num_licenses:
        logger.info(
            f'Skipping task {self.name} with id {self.request.id} '
            f'and args: {self.request.args}, kwargs: {self.request.kwargs}, '
            f'because desired_num_licenses is not set on this subscription plan.'
        )
        return
    license_count_gap = subscription_plan.desired_num_licenses - subscription_plan.num_licenses
    if license_count_gap <= 0:
        logger.info(
            f'Skipping task {self.name} with id {self.request.id} '
            f'and args: {self.request.args}, kwargs: {self.request.kwargs}, '
            f'because the actual license count ({subscription_plan.num_licenses}) '
            f'already meets or exceeds the desired license count ({subscription_plan.desired_num_licenses}).'
        )
        return

    # There's work to do, creating licenses! It should be safe to not re-check the license count between batches
    # because we lock this subscription plan anyway (via @subscription_plan_semaphore decorator).
    for batch_count in batch_counts(license_count_gap, batch_size=PROVISION_LICENSES_BATCH_SIZE):
        subscription_plan.increase_num_licenses(batch_count)


def provision_licenses(subscription):
    """
    For a given subscription plan, try to provision in synchronously or asynchronously.
    Args:
        subscription_plan: SubscriptionPlan instance
    """
    if subscription.desired_num_licenses and not subscription.last_freeze_timestamp:
        license_count_gap = subscription.desired_num_licenses - subscription.num_licenses
        if license_count_gap > 0:
            if license_count_gap <= PROVISION_LICENSES_BATCH_SIZE:
                # We can handle just one batch synchronously.
                SubscriptionPlan.increase_num_licenses(subscription, license_count_gap)
            else:
                # Multiple batches of licenses will need to be created, so provision them asynchronously.
                provision_licenses_task.delay(subscription_plan_uuid=subscription.uuid)
