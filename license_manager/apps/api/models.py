# Models that can be shared across multiple versions of the API
# should be created here. As the API evolves, models may become more
# specific to a particular version of the API. In this case, the models
# in question should be moved to versioned sub-package.

import datetime
from uuid import uuid4

from celery import current_app
from django.conf import settings
from django.db import models
from model_utils.models import TimeStampedModel

# from license_manager.apps.api.tasks import (
#     enterprise_enrollment_license_subsidy_task,
# )

from license_manager.apps.api.utils import (
    upload_file_to_s3,
    create_presigned_url,
)

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
    def create_bulk_enrollment_job(enqueuing_user_id, enterprise_customer_uuid, user_emails, course_run_keys, notify_learners, subscription_uuid = None):
        bej = BulkEnrollmentJob(enterprise_customer_uuid=enterprise_customer_uuid,lms_user_id=enqueuing_user_id).save()
        # avoid circular dependency
        # https://stackoverflow.com/a/26382812
        # enterprise_enrollment_license_subsidy_task.delay(str(bej.uuid), enterprise_uuid, user_emails, course_run_keys, notify_learners,subscription_uuid)
        current_app.send_task('api.tasks.enterprise_enrollment_license_subsidy_task', (str(bej.uuid), enterprise_uuid, user_emails, course_run_keys, notify_learners,subscription_uuid))
        return bje

    def upload_results(self, file_name):
        self.results_s3_object_name = f'{self.enterprise_customer_uuid}/{self.uuid}/Bulk-Enrollment-Results-{datetime.datetime.utcnow().isoformat()}.csv'
        results_object_uri = upload_file_to_s3(file_name, settings.BULK_ENROLL_JOB_AWS_BUCKET, object_name=self.results_s3_object_name)
        self.save()
        return results_object_uri

    def generate_download_url(self):
        return create_presigned_url(settings.BULK_ENROLL_JOB_AWS_BUCKET, self.results_s3_object_name)

