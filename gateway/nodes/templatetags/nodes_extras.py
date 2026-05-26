from django import template

register = template.Library()


@register.filter
def dict_get(d, key):
    """Zwraca wartość słownika dla podanego klucza, lub None jeśli klucz nie istnieje."""
    if isinstance(d, dict):
        return d.get(key)
    return None
