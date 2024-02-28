"""
Defines custom paginators used by subscription viewsets.
"""
from django.core.paginator import Paginator as DjangoPaginator
from django.utils.functional import cached_property
from edx_rest_framework_extensions.paginators import DefaultPagination
from rest_framework.pagination import PageNumberPagination

from license_manager.apps.api.serializers import (
    MinimalCustomerAgreementSerializer,
)
from license_manager.apps.subscriptions.models import CustomerAgreement


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


class EstimatedCountDjangoPaginator(DjangoPaginator):
    """
    A lazy paginator that determines it's count from
    the upstream `estimated_count`
    """

    def __init__(self, *args, estimated_count=None, **kwargs):
        self.estimated_count = estimated_count
        super().__init__(*args, **kwargs)

    @cached_property
    def count(self):
        if self.estimated_count is None:
            return super().count
        return self.estimated_count


class EstimatedCountLicensePagination(LicensePagination):
    """
    Allows the caller (probably the `paginator()` property
    of an upstream Viewset) to provided an `estimated_count`,
    which means the downstream django paginator does *not*
    perform an additional query to get the count of the queryset.
    """

    def __init__(self, *args, estimated_count=None, **kwargs):
        """
        Optionally stores an `estimated_count` to pass along
        to `EstimatedCountDjangoPaginator`.
        """
        self.estimated_count = estimated_count
        super().__init__(*args, **kwargs)

    def django_paginator_class(self, queryset, page_size):
        """
        This only works because the implementation of `paginate_queryset`
        treats `self.django_paginator_class` as if it is simply a callable,
        and not necessarily a class, that returns a Django Paginator instance.

        It also (safely) relies on `self` having an instance variable called `estimated_count`.
        """
        if self.estimated_count is not None:
            return EstimatedCountDjangoPaginator(
                queryset, page_size, estimated_count=self.estimated_count,
            )
        return DjangoPaginator(queryset, page_size)


class LearnerLicensesPaginationCustomerAgreement(DefaultPagination):
    """
    Adds the customer agreement object to the learner-licenses endpoint.
    The learner licenses endpoint currently contains the subscription_licenses, with its
    corresponding subscription_plan. In order to reduce the number of calls to the client,
    we incorporate the customer_agreement accessible within a single call.
    """

    def get_paginated_response(self, data):
        """
        Modifies the DefaultPagination response to include ``customer_agreement`` dict.

        Arguments:
            self: LearnerLicensesPaginationCustomerAgreement instance.
            data (dict): Results for current page.

        Returns:
            (Response): DRF response object containing ``customer_agreement`` dict.
        """
        paginated_response = super().get_paginated_response(data)
        enterprise_customer_uuid = self.request.query_params.get('enterprise_customer_uuid')
        try:
            customer_agreement = CustomerAgreement.objects.get(enterprise_customer_uuid=enterprise_customer_uuid)
            paginated_response.data.update({
                'customer_agreement': MinimalCustomerAgreementSerializer(customer_agreement).data
            })
        except CustomerAgreement.DoesNotExist:
            paginated_response.data.update({
                'customer_agreement': None
            })

        return paginated_response
