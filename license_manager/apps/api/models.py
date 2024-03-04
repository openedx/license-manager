"""
Models that can be shared across multiple versions of the API
should be created here. As the API evolves, models may become more
specific to a particular version of the API. In this case, the models
in question should be moved to versioned sub-package.
"""
import datetime
import logging
from uuid import uuid4

from celery import current_app
from django.conf import settings
from django.db import models
from model_utils.models import TimeStampedModel

from license_manager.apps.api.utils import (
    create_presigned_url,
    upload_file_to_s3,
)
from license_manager.apps.subscriptions import constants
from license_manager.apps.subscriptions.models import License


logger = logging.getLogger(__name__)


class BulkEnrollmentJob(TimeStampedModel):
    """
    An object to track async Bulk Enrollment tasks
     .. no_pii:
    """
    uuid = models.UUIDField(
        primary_key=True,
        default=uuid4,
        editable=False,
        unique=True,
    )

    enterprise_customer_uuid = models.UUIDField(
        null=False,
        blank=False,
        unique=False,
    )

    lms_user_id = models.IntegerField(
        blank=True,
        null=True,
    )

    results_s3_object_name = models.CharField(
        max_length=255,
        blank=True,
        null=True,
        unique=False,
    )

    @classmethod
    def create_bulk_enrollment_job(
        cls,
        enqueuing_user_id,
        enterprise_customer_uuid,
        user_emails,
        course_run_keys,
        notify_learners,
        subscription_uuid=None,
        enroll_all=None,
    ):
        """
        Creates an asynchronous ``enterprise_enrollment_license_subsidy_task``
        for the given batch of (users, courses).
        """
        # If enroll all is supplied, a subscription uuid must be provided.
        if enroll_all:
            if subscription_uuid:
                user_emails = list(License.objects.filter(
                    subscription_plan__in=[subscription_uuid],
                    status__in=[constants.ACTIVATED, constants.ASSIGNED]
                ).values_list('user_email', flat=True))
            else:
                raise Exception(
                    'create_bulk_enrollment_job requires subscription_uuid when enroll_all is provided'
                )

        bulk_enrollment_job = cls(
            enterprise_customer_uuid=enterprise_customer_uuid,
            lms_user_id=enqueuing_user_id,
            uuid=uuid4()
        )
        bulk_enrollment_job.save()
        logger.info(
            'enqueuing enterprise_enrollment_license_subsidy_task '
            f'for bulk_enrollment_job_uuid={str(bulk_enrollment_job.uuid)}'
        )
        # avoid circular dependency
        # https://stackoverflow.com/a/26382812
        current_app.send_task(
            'license_manager.apps.api.tasks.enterprise_enrollment_license_subsidy_task',
            (
                str(bulk_enrollment_job.uuid),
                str(enterprise_customer_uuid),
                user_emails,
                course_run_keys,
                notify_learners,
                subscription_uuid,
            ),
        )
        return bulk_enrollment_job

    def upload_results(self, file_name):
        """
        Upload results in the given file_name to an S3 bucket.
        """
        if hasattr(settings, "BULK_ENROLL_JOB_AWS_BUCKET") and settings.BULK_ENROLL_JOB_AWS_BUCKET:
            self.results_s3_object_name = (
                f'{self.enterprise_customer_uuid}/{self.uuid}/Bulk-Enrollment-Results-'
                f'{datetime.datetime.utcnow().isoformat()}.csv'
            )
            results_object_uri = upload_file_to_s3(
                file_name,
                settings.BULK_ENROLL_JOB_AWS_BUCKET,
                object_name=self.results_s3_object_name,
            )
            self.save()
            return results_object_uri
        else:
            return None

    def generate_download_url(self):
        """
        Generates an S3 download link for the results of this job.
        """
        if self.results_s3_object_name:
            return create_presigned_url(settings.BULK_ENROLL_JOB_AWS_BUCKET, self.results_s3_object_name)
        else:
            return None
