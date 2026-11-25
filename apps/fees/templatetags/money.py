from django import template

from apps.fees.models import rupees as format_rupees
from apps.fees.models import rupees_short as format_rupees_short

register = template.Library()


@register.filter
def rupees(paise):
    """{{ invoice.total_paise|rupees }} -> ₹12,500.00"""
    return "" if paise in (None, "") else format_rupees(int(paise))


@register.filter
def rupees_short(paise):
    """{{ fees.billed|rupees_short }} -> ₹1.13 Cr, for headline figures."""
    return "" if paise in (None, "") else format_rupees_short(int(paise))
