# libretro-cores

libretro cores, built from pinned upstream sources and shipped as a single
conan package. A libretro core is a shared library with a fixed C
entry-point set (`retro_api_version`, `retro_get_system_info`, `retro_run`,
...): a front-end loads one at run time with `dlopen` and talks to it
through `libretro.h`, and never links against it. This project turns that
into something a C++ build can depend on — one `find_package` away from the
absolute path of a core and the header that describes it.

The package, `libretro-cores`, holds

    lib/<core>_libretro.so
    include/<core>/libretro.h
    licenses/libretro-cores/<core>.txt
    share/cmake/libretro-cores/<core>.cmake

Today there is one core: Genesis Plus GX (Sega Master System, Game Gear,
Mega Drive / Genesis, Sega CD), pinned to an upstream commit and carrying
three save-state patches described under [Releasing](#releasing).

## Requirements

Linux on x86_64. Only the Linux core is wired up; `Makefile.libretro` has
other platforms and adding one is a small change to a module's
`configure.py`.

Python 3.11 or newer, [buildutil](https://github.com/2bitsin/buildutil),
CMake 3.25 or newer, `ninja`, `make`, `patch`, `tar`, and a C++20 compiler.
buildutil drives conan, cmake and ninja, and builds its own `_pyvenv/`
beside the checkout on the first command, so conan is not something to
install.

The first build needs outbound https to `github.com`: the module's
`configure.py` downloads the pinned upstream tarball. Afterwards the
archive is cached in the build tree and the build is offline.

## Build it

    ./buildutil build
    ./buildutil test

Nothing else — no fetch step, no submodule init. `configure.py` downloads
the pinned tarball, checks it against a committed sha256, unpacks it under
`_build/generated/`, applies the module's patches and runs the core's own
`Makefile.libretro`.

`buildutil test` runs the module's own tests — they dlopen the core just
built and assert the libretro API version — and then the conan package
test, which does the same thing through `find_package` against a cached
package.

## How a consumer gets the core path

Nothing in this package is linkable. Every libretro core exports the same
`retro_*` symbols, so a consumer could link at most one of them and would
still have to load the rest by path. `cpp_info.libs` is therefore empty and
the package hands over paths instead.

`find_package(libretro-cores CONFIG)` pulls in the shipped cmake module and
defines, per core:

    LIBRETRO_CORES_GENESIS_PLUS_GX   absolute path of the .so

A buildutil consumer that wants the cores copied next to its binaries names
the package in its `buildutil.toml`:

    [runtime]
    from = ["libretro-cores"]

which picks up the GLOBAL property `LIBRETRO_CORES_RUNTIME_LIBRARY_DIR` the
same cmake module publishes — the directory holding every core.

At run time without cmake, the recipe also exports `LIBRETRO_CORES_DIR` into
the conan run environment.

Headers come from the package's `include/`, spelled by core:

    #include <genesis-plus-gx/libretro.h>

`test_package/` is a complete worked example of all of this: twenty lines of
cmake and one `smoke.cpp` that resolves the path, compiles against the
header and dlopens the core.

## Adding a core

Copy `sources/genesis-plus-gx/` to `sources/<core>/` and change four things
in its `configure.py`: `COMMIT`, `SHA256`, the upstream URL and the built
artifact's name. Commit the core's own `libretro.h` beside it — the build
refuses to run if it is not the pinned tree's copy — and write a
`<core>.test.cpp`. The module's `CMakeLists.txt` stays a bare
`Init_submodule()`.

Cores whose makefile is not `Makefile.libretro platform=unix` need that line
changed too; nothing else in the project knows how a core is built.

## Releasing

The pin is `COMMIT`/`SHA256` in a module's `configure.py`. Moving it is the
release:

1. update `COMMIT` and `SHA256`, copy the new tree's `libretro.h` over the
   committed one,
2. `./buildutil test`,
3. add an entry to [Release notes](#release-notes), commit, and tag
   `YYYY.M.D` — the upstream commit's date, bare, no `v` prefix.

A change to the pinned tree itself is a patch: a `*.patch` file in the
module's `patches/`, applied with `patch -p1` in name order right after the
unpack, headed by at most six lines saying what it changes, why, and the
upstream issue if one exists. The unpack stamp is the commit plus the sha256
of every patch, so editing or adding one re-unpacks and re-applies instead
of applying twice. A patch is part of the pin, and re-tagging publishes it
the same way moving `COMMIT` does.

Genesis Plus GX carries three, all of them state the pinned tree saves
nothing of and `state_load`'s `system_reset` puts back to reset values:

- `0001` the 6-button gamepad context (`core/input_hw/gamepad.c`),
- `0002` `m68k.refresh_cycles`, the next 68000 bus refresh stall,
- `0003` `fm_cycles_busy`, the cycle the YM2612 BUSY flag clears at.

A change to the recipe, the cmake module or a `configure.py` that does NOT
move a tag still makes a new conan recipe revision, and consumers resolve
the newest revision — so every published binary under the version has to be
rebuilt and re-uploaded under it. Re-tagging (move the tag, push it) is the
way to do that.

## Package id

`package_id()` drops compiler and build_type. The cores come out of their
own makefiles and never see the consumer's toolchain, so a debug consumer
and a release consumer resolve one binary that depends only on os and arch.

## Release notes

**2026.9.12 — the first public release.** Genesis Plus GX pinned at
`c2838c7`, with the three save-state patches above, packaged for conan and
reachable through `find_package`.

## Licence

The build machinery in this repository — the conan recipe, the module
`configure.py`, the cmake glue, the tests and the patches — is MIT, see
[LICENSE](LICENSE). Copyright (c) 2026 Aleksandr Ševčenko.

That is not the licence of what it builds, and the difference matters:

- **Genesis Plus GX** is under the [Genesis Plus GX
  licence](https://github.com/libretro/Genesis-Plus-GX/blob/master/LICENSE.txt)
  — copyright (c) 1998-2003 Charles MacDonald, (c) 2007-2026 Eke-Eke, with
  portions from the MAME team. It permits redistribution and derivative
  works, and it **forbids selling a redistribution or using one in a
  commercial product or activity**; a modified redistribution must carry
  complete source. The built `genesis_plus_gx_libretro.so` is a derivative
  work of that source and carries those terms, so anyone shipping this
  package's binary is bound by them, not by the MIT text above. The package
  ships the full licence at `licenses/libretro-cores/genesis-plus-gx.txt`.
- **`libretro.h`**, the API header vendored per core, is MIT, copyright (c)
  2010-2020 The RetroArch team; the notice is at the top of the file.
