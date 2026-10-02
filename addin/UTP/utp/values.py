"""Reading and comparing the values a preset drives.

The add-in carries no list of parameter names. Measured across 202 real
presets, not one parameter appears on all of them: probing presets hold
tool_feedProbeLink, turning holds tool_useConstantSurfaceSpeed, milling holds
the cutting feeds. There is no common core to write down, and two earlier
attempts at writing one were both wrong.

So for any pair it compares whatever both sides actually have.
"""

from . import config


def scalars(owner):
    """Every readable plain-valued parameter, as name -> value.

    Geometry and view parameters hand back a new object on every read, so
    they always look changed; only plain values are kept.
    """
    out = {}
    try:
        parameters = owner.parameters
    except Exception:
        return out
    for index in range(parameters.count):
        try:
            parameter = parameters.item(index)
            value = parameter.value.value
        except Exception:
            continue
        if isinstance(value, config.COMPARABLE_TYPES):
            out[parameter.name] = value
    return out


def named(owner, names):
    """The values of just these parameters, looked up by name.

    An operation carries about three hundred readable parameters and a
    preset about fifteen, and only the ones both have are ever compared. So
    reading all three hundred threw away nine tenths of the work: the preset
    is read first and the operation is then asked only for those names.
    """
    out = {}
    try:
        parameters = owner.parameters
    except Exception:
        return out
    for name in names:
        try:
            parameter = parameters.itemByName(name)
            if parameter is None:
                continue
            value = parameter.value.value
        except Exception:
            continue
        if isinstance(value, config.COMPARABLE_TYPES):
            out[name] = value
    return out


def _same(a, b):
    if isinstance(a, bool) or isinstance(b, bool):
        return a == b
    if isinstance(a, (int, float)) and isinstance(b, (int, float)):
        # Relative, not absolute. A feed of 1002 mm/min compared to nine
        # decimal places would call recomputation noise a real difference.
        scale = max(abs(a), abs(b), 1.0)
        return abs(a - b) <= config.TOLERANCE * scale
    return a == b


def differences(left, right):
    """Names held by both whose values disagree.

    Floats get room proportional to their size, because Fusion recomputes
    linked values and they do not come back bit for bit.
    """
    return sorted(name for name in set(left) & set(right)
                  if not _same(left[name], right[name]))


def detail(left, right, names, limit=8):
    """What actually moved, as name -> "before -> after".

    Without the numbers a report cannot tell a real override from rounding,
    which is exactly the question the first real run raised.
    """
    out = {}
    for name in names[:limit]:
        out[name] = "%s -> %s" % (_short(left.get(name)), _short(right.get(name)))
    return out


def _short(value):
    if isinstance(value, float):
        return round(value, 4)
    return value
