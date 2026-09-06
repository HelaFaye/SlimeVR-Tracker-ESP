# Setting up to run the checks

`./VERIFY.sh` runs everything. None of it needs a PlatformIO toolchain, megaTinyCore, or
hardware — it is all host builds, static analysis and generation.

## Arch Linux

```sh
sudo pacman -S base-devel python avr-gcc avr-libc clang cppcheck
sudo pacman -S kicad kicad-library          # kicad-library is a separate package

python -m venv .venv && source .venv/bin/activate
pip install kiutils jsonschema clang-format==17.0.6
```

Four Arch-specific things worth knowing:

**Python is externally managed.** `pip install` into the system Python is blocked. Use the
venv above, or `pipx install clang-format==17.0.6` for the standalone tool. Passing
`--break-system-packages` works but you will regret it eventually.

**clang-format will be too new.** Arch ships whatever is current (20+); CI pins **17**, and
the two disagree about line breaking. Running the newer one produces violations that are
not violations. `VERIFY.sh` detects the mismatch and says so rather than failing silently
— but install 17 in the venv and the check becomes meaningful.

**avr-gcc is very new** (16.x versus the 7.3 this was developed against). That is good — it
is stricter. If it produces warnings the older compiler did not, they are probably real.

**KiCad is version 10**, and these generators were written against 7. Consequences:
`kicad-library` puts symbols in `/usr/share/kicad/symbols`, which is where `verify.py`
looks, so that part is fine. But the generated `.kicad_sch` files declare the KiCad 7
format version (`20230121`); KiCad 10 will open and silently migrate them, which is
expected and harmless — just do not be surprised when the file changes on first save.
`kikit` compatibility with KiCad 10 is **not verified here**; check before relying on the
panel step.

**Stock symbols move between KiCad versions.** `Device:Q_PMOS_GSD` exists in 7 and not in
10. Parts likely to drift list alternatives separated by `|`.

A candidate is only accepted if it **both exists and has the required pin order**. Parts
declare `pin_functions` (for the MOSFET: pin 1 = G, 2 = S, 3 = D, per the DMG2305UX in
SOT-23) and `verify.py` reads the actual pin names out of the installed symbol and
compares. KiCad ships all four orderings — `Q_PMOS_GSD`, `GDS`, `DGS`, `DSG` — so
resolving on existence alone would happily pick one that drives the wrong pad. Resolving
on pin function cannot.

This used to be a manual check-the-datasheet caveat. It is now automatic, and
`test_pin_order.py` proves the guard fires by deliberately breaking it four ways.

If your libraries are somewhere else, override the search:

```sh
export KICAD_SYMBOL_DIR=/path/to/symbols
export KICAD_FOOTPRINT_DIR=/path/to/footprints
```

## Debian / Ubuntu

```sh
sudo apt install build-essential python3 python3-venv gcc-avr avr-libc \
                 clang-format-17 cppcheck kicad-symbols kicad-footprints
python3 -m venv .venv && . .venv/bin/activate
pip install kiutils jsonschema
```

`kicad-symbols` and `kicad-footprints` are separate from `kicad` here too, and
`--no-install-recommends` on `kicad` will skip them.

## What each check needs

| Check | Needs | If missing |
|---|---|---|
| Chain simulation | `g++` with C++20 | skipped |
| Numeric verification | python3 only | always runs |
| Node firmware variants | `avr-gcc`, `avr-libc` | skipped |
| KiCad symbols/footprints | KiCad libraries on disk | fails, with install hints |
| Board config generation | `jsonschema` | fails |
| Formatting | `clang-format` (ideally 17) | skipped, or warns on version |

Missing tools are skipped with a note rather than failing the run, so a partial toolchain
still gets you partial coverage.

## Not covered by any of this

The target builds. `pio run` for the ESP32-C5 envs and a megaTinyCore build of the node
firmware both need network access to package registries and have never been run. Every
check here is a host build; passing them says the logic and the numbers are right, not
that it compiles for the part.
