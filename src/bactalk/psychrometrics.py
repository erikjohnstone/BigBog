"""Psychrometric functions shared by the IR interpreter and the Shadow Runtime kernels.

``wet_bulb`` is CDL ``Psychrometrics.WetBulb_TDryBulPhi``: Stull's (2011) closed-form
approximation of the wet-bulb temperature from dry-bulb temperature and relative
humidity. The Open Control Engine evaluates it with the Rust ``libm`` crate, whose
``atan`` is fdlibm's; Java's ``StrictMath.atan`` is fdlibm's too. ``fdlibm_atan`` below
is a line-for-line port so the Python and Java kernels agree bit for bit. The
``rh^1.5`` term is written as ``rh * sqrt(rh)`` in both ports (``sqrt`` is correctly
rounded everywhere); it can differ from the engine's ``pow`` by at most one unit in the
last place, far inside the differential's bands.
"""

from __future__ import annotations

import math
import struct

KELVIN_OFFSET = 273.15

_ATAN_HI = (
    4.63647609000806093515e-01,
    7.85398163397448278999e-01,
    9.82793723247329054082e-01,
    1.57079632679489655800e00,
)
_ATAN_LO = (
    2.26987774529616870924e-17,
    3.06161699786838301793e-17,
    1.39033110312309984516e-17,
    6.12323399573676603587e-17,
)
_AT = (
    3.33333333333329318027e-01,
    -1.99999999998764832476e-01,
    1.42857142725034663711e-01,
    -1.11111104054623557880e-01,
    9.09088713343650656196e-02,
    -7.69187620504482999495e-02,
    6.66107313738753120669e-02,
    -5.83357013379057348645e-02,
    4.97687799461593236017e-02,
    -3.65315727442169155270e-02,
    1.62858201153657823623e-02,
)


def _high_word(value: float) -> int:
    bits = struct.unpack(">q", struct.pack(">d", value))[0]
    return (bits >> 32) & 0xFFFFFFFF


def fdlibm_atan(x: float) -> float:
    """fdlibm ``s_atan.c``, the algorithm behind Java ``StrictMath.atan`` and ``libm``."""

    hx = _high_word(x)
    negative = hx >= 0x80000000
    ix = hx & 0x7FFFFFFF
    if ix >= 0x44100000:  # |x| >= 2^66
        if math.isnan(x):
            return x + x
        return -(_ATAN_HI[3] + _ATAN_LO[3]) if negative else _ATAN_HI[3] + _ATAN_LO[3]
    if ix < 0x3FDC0000:  # |x| < 0.4375
        if ix < 0x3E200000:  # |x| < 2^-29
            return x
        index = -1
    else:
        x = abs(x)
        if ix < 0x3FF30000:  # |x| < 1.1875
            if ix < 0x3FE60000:  # 7/16 <= |x| < 11/16
                index = 0
                x = (2.0 * x - 1.0) / (2.0 + x)
            else:  # 11/16 <= |x| < 19/16
                index = 1
                x = (x - 1.0) / (x + 1.0)
        elif ix < 0x40038000:  # |x| < 2.4375
            index = 2
            x = (x - 1.5) / (1.0 + 1.5 * x)
        else:  # 2.4375 <= |x| < 2^66
            index = 3
            x = -1.0 / x
    z = x * x
    w = z * z
    s1 = z * (_AT[0] + w * (_AT[2] + w * (_AT[4] + w * (_AT[6] + w * (_AT[8] + w * _AT[10])))))
    s2 = w * (_AT[1] + w * (_AT[3] + w * (_AT[5] + w * (_AT[7] + w * _AT[9]))))
    if index < 0:
        return x - x * (s1 + s2)
    z = _ATAN_HI[index] - ((x * (s1 + s2) - _ATAN_LO[index]) - x)
    return -z if negative else z


def _sqrt(value: float) -> float:
    # IEEE (and Java) sqrt of a negative is NaN; Python's math.sqrt raises instead.
    return math.sqrt(value) if value >= 0.0 else math.nan


def wet_bulb(dry_bulb_kelvin: float, relative_humidity: float) -> float:
    """Wet-bulb temperature [K] from dry-bulb [K] and relative humidity [1]."""

    if not math.isfinite(dry_bulb_kelvin) or not math.isfinite(relative_humidity):
        return math.nan
    t_c = dry_bulb_kelvin - KELVIN_OFFSET
    rh = 100.0 * relative_humidity
    if not math.isfinite(rh):
        return math.nan
    return (
        KELVIN_OFFSET
        + t_c * fdlibm_atan(0.151977 * _sqrt(rh + 8.313659))
        + fdlibm_atan(t_c + rh)
        - fdlibm_atan(rh - 1.676331)
        + 0.00391838 * (rh * _sqrt(rh)) * fdlibm_atan(0.023101 * rh)
        - 4.686035
    )


__all__ = ["KELVIN_OFFSET", "fdlibm_atan", "wet_bulb"]
