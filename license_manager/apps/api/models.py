# Models that can be shared across multiple versions of the API
# should be created here. As the API evolves, models may become more
# specific to a particular version of the API. In this case, the models
# in question should be moved to versioned sub-package.

from uuid import uuid4

from django.db import models
from model_utils.models import TimeStampedModel

from license_manager.apps.api.tasks import (
    enterprise_enrollment_license_subsidy_task,
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

    @classmethod
    def create_bulk_enrollment_job(enqueuing_user_id, enterprise_customer_uuid, user_emails, course_run_keys, notify_learners, subscription_uuid = None):
        bej = BulkEnrollmentJob(enterprise_customer_uuid=enterprise_customer_uuid,lms_user_id=enqueuing_user_id).save()
        enterprise_enrollment_license_subsidy_task.delay(str(bej.uuid), enterprise_uuid, user_emails, course_run_keys, notify_learners,subscription_uuid)
        return bje