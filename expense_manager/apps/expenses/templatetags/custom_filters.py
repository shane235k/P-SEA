from django import template

register = template.Library()

@register.filter(name='absolute')
def absolute(value):
    """
    Returns the absolute value of a number (Decimal, float, int, etc.).
    """
    try:
        return abs(value)
    except (TypeError, ValueError):
        return value
