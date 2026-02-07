#!/usr/bin/env python3
"""
Read VOLUME_CONV from test.conf, build VolumeConverter,
plot Volume (uL) vs Steps (x-axis), and report slopes.
"""
import sys
from configparser import ConfigParser, ExtendedInterpolation
import numpy as np
import matplotlib.pyplot as plt
from numpy.polynomial import Polynomial
from volume_converter import VolumeConverter


def parse_float_list(s: str) -> list[float]:
    return [float(tok.strip()) for tok in s.split(",") if tok.strip()]


def volume_from_steps(s, a0, a1, a2, max_vol):
    """
    Invert steps = a0 + a1*v + a2*v^2  ->  v(s).
    Picks the physically valid root in [0, max_vol].
    Falls back to linear inversion if a2 ~ 0.
    """
    s = np.asarray(s, dtype=float)

    if abs(a2) < 1e-12:
        # Linear case: steps = a0 + a1*v  -> v = (s - a0)/a1
        return (s - a0) / a1

    a, b, c = a2, a1, a0 - s
    disc = b * b - 4 * a * c
    sqrt_disc = np.sqrt(np.maximum(disc, 0.0))

    v1 = (-b + sqrt_disc) / (2 * a)
    v2 = (-b - sqrt_disc) / (2 * a)

    # Prefer the root that lies in [0, max_vol]
    v = np.where((v1 >= 0) & (v1 <= max_vol), v1, v2)
    # If discriminant < 0, mark as NaN (won't plot)
    v = np.where(disc >= 0, v, np.nan)
    return v


def main(conf_path: str = "test.conf") -> None:
    # --- load config ---
    cfg = ConfigParser(interpolation=ExtendedInterpolation())
    with open(conf_path, "r") as f:
        cfg.read_file(f)

    vols = parse_float_list(cfg["VOLUME_CONV"]["volumes"])  # uL
    steps = parse_float_list(cfg["VOLUME_CONV"]["steps"])   # steps
    max_vol = float(cfg["VOLUME_CONV"].get("max_vol", max(vols)))

    if len(vols) != len(steps):
        raise ValueError(f"volumes and steps must be same length: {len(vols)} vs {len(steps)}")

    # --- fit using class (degree=2 in __init__) ---
    vc = VolumeConverter(vols, steps)

    # Use the fitted polynomial; rewrap with 'uL' symbol for pretty printing
    P = Polynomial(vc._poly.coef, domain=vc._poly.domain, window=vc._poly.window, symbol="uL")
    print("Fitted polynomial (steps = f(uL)):")
    print(P)  # e.g., a0 + a1·uL + a2·uL²
    print("coefficients:", P.coef)

    # Coeffs for inversion
    coefs = P.coef
    a0 = float(coefs[0])
    a1 = float(coefs[1]) if len(coefs) > 1 else 0.0
    a2 = float(coefs[2]) if len(coefs) > 2 else 0.0

    # --- plot Volume (µL) vs Steps (flip axes) ---
    s_min, s_max = float(np.min(steps)), float(np.max(steps))
    s_grid = np.linspace(s_min, s_max, 600)
    v_grid = volume_from_steps(s_grid, a0, a1, a2, max_vol=max_vol)

    plt.figure()
    plt.plot(s_grid, v_grid, label="Model: uL(steps)")
    plt.scatter(steps, vols, s=24, label="Calibration")
    plt.xlabel("Motor steps (µsteps)")
    plt.ylabel("Volume (µL)")
    plt.title("Volume vs Steps")
    plt.legend()
    plt.tight_layout()
    # plt.savefig("volume_vs_steps.png", dpi=200, bbox_inches="tight")
    plt.show()

    # --- Slopes ---
    # ds/duL (instantaneous steps per µL) from the derivative of steps=f(uL)
    dP = P.deriv()
    slopes_ds_dv_at_cal = dP(np.array(vols))

    print("\nInstantaneous steps/µL (ds/duL) at calibration points:")
    print(" idx |   volume (uL) |   ds/duL")
    print("-----+---------------+-----------")
    for i, (v, m) in enumerate(zip(vols, slopes_ds_dv_at_cal), start=1):
        print(f"{i:>3} | {v:13.3f} | {m:9.6f}")

    # duL/dstep = 1 / (ds/duL) evaluated at the same volumes
    inv_slopes_duL_ds_at_cal = 1.0 / slopes_ds_dv_at_cal
    print("\nInstantaneous µL/step (duL/dstep) at calibration points:")
    print(" idx |   volume (uL) |  duL/dstep")
    print("-----+---------------+------------")
    for i, (v, m) in enumerate(zip(vols, inv_slopes_duL_ds_at_cal), start=1):
        print(f"{i:>3} | {v:13.3f} | {m:11.6f}")

    # Optional: plot duL/dstep vs steps across the grid
    # Map each s_grid to its corresponding volume v_grid, then du/ds = 1/(ds/dv at v)
    slopes_ds_dv_grid = dP(v_grid)
    with np.errstate(divide='ignore', invalid='ignore'):
        inv_slopes_duL_ds_grid = 1.0 / slopes_ds_dv_grid

    plt.figure()
    plt.plot(s_grid, inv_slopes_duL_ds_grid, label="duL/dstep")
    plt.xlabel("Motor steps (µsteps)")
    plt.ylabel("µL per step")
    plt.title("Instantaneous µL per Step vs Steps")
    plt.legend()
    plt.tight_layout()
    # plt.savefig("ul_per_step_vs_steps.png", dpi=200, bbox_inches="tight")
    plt.show()


if __name__ == "__main__":
    path = sys.argv[1] if len(sys.argv) > 1 else "test.conf"
    main(path)
