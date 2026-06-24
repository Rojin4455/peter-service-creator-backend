"""Persist customer package picks on a submission."""

from django.shortcuts import get_object_or_404

from service_app.models import Package
from quote_app.models import CustomerPackageQuote, CustomerServiceSelection
from quote_app.pricing_utils import recalculate_submission_totals


def sync_package_selections(submission, selected_packages, *, recalculate=True):
    """
    Save package choices for each service selection.

    selected_packages: list of dicts with service_selection_id + package_id
    """
    if not selected_packages:
        return submission

    for package_data in selected_packages:
        service_selection = get_object_or_404(
            CustomerServiceSelection,
            id=package_data['service_selection_id'],
            submission=submission,
        )
        package = get_object_or_404(Package, id=package_data['package_id'])

        if package.service_id != service_selection.service_id:
            raise ValueError(
                f'Package {package.name} does not belong to service {service_selection.service.name}'
            )

        quote = get_object_or_404(
            CustomerPackageQuote,
            service_selection=service_selection,
            package=package,
        )

        service_selection.selected_package = package
        service_selection.final_base_price = quote.base_price + quote.sqft_price
        service_selection.final_sqft_price = quote.sqft_price
        service_selection.final_total_price = quote.effective_total_price
        service_selection.save()

        service_selection.package_quotes.update(is_selected=False)
        quote.is_selected = True
        quote.save()

    if submission.status in ('draft', 'submitted'):
        submission.status = 'packages_selected'
    submission.save(update_fields=['status', 'updated_at'])

    if recalculate:
        recalculate_submission_totals(submission)

    return submission
