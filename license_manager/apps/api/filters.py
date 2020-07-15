"""
Filters for the License API.
"""

from django_filters import rest_framework as filters

from license_manager.apps.subscriptions.models import License


class LicenseStatusFilter(filters.FilterSet):
    """Filter for License Status"""
    status = filters.CharFilter(method='filter_by_status')

    class Meta:
        model = License
        fields = ['status']

    def filter_by_status(self, queryset, name, value):  # pylint: disable=unused-argument
        status_values = value.strip().split(',')
        return queryset.filter(status__in=status_values).distinct()
