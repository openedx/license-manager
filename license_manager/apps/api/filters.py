"""
Filters for the License API.
"""

from django_filters import rest_framework as filters

from license_manager.apps.subscriptions.models import License


class LicenseFilter(filters.FilterSet):
    """
    Filter for License.

    Supports filtering by license status and whether null emails are included.
    """
    status = filters.CharFilter(method='filter_by_status')
    ignore_null_emails = filters.BooleanFilter(method='filter_by_ignore_null_emails')

    class Meta:
        model = License
        fields = ['status']

    def filter_by_status(self, queryset, name, value):  # pylint: disable=unused-argument
        status_values = value.strip().split(',')
        return queryset.filter(status__in=status_values).distinct()

    def filter_by_ignore_null_emails(self, queryset, name, value):  # pylint: disable=unused-argument
        if not value:
            return queryset
        return queryset.exclude(user_email__isnull=True)
