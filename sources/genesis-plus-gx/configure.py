"""The pinned Genesis Plus GX core: fetch, verify, patch, build, place.

Moving COMMIT and SHA256 below is the release; nothing else in this
project names a version of the upstream sources.
"""

import hashlib
import os
import shutil
import tarfile
import urllib.request
from pathlib import Path

import buildutil_configure as cfg

COMMIT = 'c2838c7dc4236fc2fe94e5dbd08b41486067918e'
SHA256 = '7ba2eab9d6dae71bb42e8208573300ad3475a4263e860178c4d19c36d85fc92b'
URL = f'https://github.com/libretro/Genesis-Plus-GX/archive/{COMMIT}.tar.gz'

PATCHES = 'patches'
CORE = 'genesis_plus_gx_libretro.so'
UPSTREAM_HEADER = 'libretro/libretro-common/include/libretro.h'
PACKAGE = 'libretro-cores'


def digest(path: Path) -> str:
  with path.open('rb') as stream:
    return hashlib.file_digest(stream, 'sha256').hexdigest()


def tarball() -> Path:
  """The pinned archive, in the profile-agnostic root so one download
  serves every build type."""
  archive = cfg.output_dir(shared=True)/f'{COMMIT}.tar.gz'
  if archive.is_file() and digest(archive) == SHA256:
    return archive
  partial = archive.with_suffix('.part')
  try:
    urllib.request.urlretrieve(URL, partial)
  except OSError as error:
    raise SystemExit(
      f'genesis-plus-gx: cannot fetch the pinned upstream source.\n'
      f'  {URL}\n  {error}\n'
      f'  this build needs network access to github.com the first time; '
      f'afterwards the archive is cached in {archive.parent}')
  found = digest(partial)
  if found != SHA256:
    partial.unlink()
    raise SystemExit(
      f'genesis-plus-gx: {URL}\n  sha256 is {found},\n  configure.py pins '
      f'{SHA256}.\n  Either github re-rolled the archive or the pin is '
      f'wrong; verify the commit before touching SHA256.')
  partial.replace(archive)
  return archive


def patch_files() -> list[Path]:
  """Every patch this module applies to the pinned tree, in name order."""
  return cfg.inputs('*.patch', root=cfg.source_dir()/PATCHES)


def pin(patches: list[Path]) -> str:
  """What the unpacked tree is: the commit and every patch on top of it.
  A patch that changes has to re-unpack, because applying it again to an
  already-patched tree is not what a changed patch means."""
  return '\n'.join([COMMIT] + [f'{p.name} {digest(p)}' for p in patches])


def apply_patches(tree: Path, patches: list[Path]) -> None:
  if not patches:
    return
  program = cfg.tool('patch', install='apt-get install patch')
  for source in patches:
    cfg.run([program, '-p1', '-i', source],
            what=f'applying {PATCHES}/{source.name}', cwd=tree)


def unpack(archive: Path, patches: list[Path]) -> Path:
  """The upstream tree, patched, shared across profiles: Makefile.libretro
  builds in-tree and its output does not vary by build type, so one tree
  is one build instead of one per profile."""
  tree = cfg.output_dir(shared=True)/'upstream'
  stamp = tree/'.pinned-commit'
  wanted = pin(patches)
  if stamp.is_file() and stamp.read_text().strip() == wanted:
    return tree
  staging = tree.parent/'_unpack'
  shutil.rmtree(staging, ignore_errors=True)
  shutil.rmtree(tree, ignore_errors=True)
  with tarfile.open(archive) as tar:
    tar.extractall(staging, filter='data')
  roots = list(staging.iterdir())
  if len(roots) != 1:
    raise SystemExit(
      f'genesis-plus-gx: {archive.name} does not hold a single root '
      f'directory: {sorted(p.name for p in roots)}')
  roots[0].replace(tree)
  shutil.rmtree(staging, ignore_errors=True)
  apply_patches(tree, patches)
  stamp.write_text(wanted + '\n')
  return tree


def check_header(tree: Path) -> None:
  """The committed libretro.h is the package's public header, so it has
  to be the pinned tree's own copy."""
  ours = cfg.source_dir()/'libretro.h'
  cfg.depends(ours)
  theirs = tree/UPSTREAM_HEADER
  if ours.read_bytes() != theirs.read_bytes():
    raise SystemExit(
      f'genesis-plus-gx: {ours} differs from the pinned tree\'s '
      f'{UPSTREAM_HEADER}.\n  Moving the pin moves the header: copy it '
      f'over and commit it with the new COMMIT/SHA256.')


def build(tree: Path) -> Path:
  make = cfg.tool('make', install='apt-get install make')
  # Upstream's own default is GIT_VERSION=" <short sha>", quotes included:
  # make strips leading whitespace after '=', and the space is what
  # separates the version from the hash in retro_get_system_info().
  cfg.run([make, '-f', 'Makefile.libretro', 'platform=unix',
           f'GIT_VERSION=" {COMMIT[:7]}"', f'-j{os.cpu_count() or 1}'],
          what='the Genesis Plus GX libretro build', cwd=tree)
  return tree/CORE


def place(built: Path, tree: Path) -> Path:
  """Everything the package ships, laid out as the package: an *.install/
  tree in the generated root is prefix-rooted, so lib/ and licenses/ and
  share/ land where conan expects them with nothing declared."""
  payload = cfg.data_dir('package.install')
  core = payload/'lib'/CORE
  core.parent.mkdir(parents=True, exist_ok=True)
  if not (core.is_file() and core.stat().st_size == built.stat().st_size
          and digest(core) == digest(built)):
    shutil.copy2(built, core)
  cfg.declare(core)
  cfg.emit_bytes(f'package.install/licenses/{PACKAGE}/genesis-plus-gx.txt',
                 (tree/'LICENSE.txt').read_bytes())
  return core


CONSUMER_MODULE = f'''\
# Written by sources/genesis-plus-gx/configure.py.
get_filename_component(_libretro_cores_prefix
  "${{CMAKE_CURRENT_LIST_DIR}}/../../.." ABSOLUTE)
set(LIBRETRO_CORES_GENESIS_PLUS_GX
  "${{_libretro_cores_prefix}}/lib/{CORE}" CACHE FILEPATH
  "absolute path of the Genesis Plus GX libretro core")
set_property(GLOBAL PROPERTY LIBRETRO_CORES_RUNTIME_LIBRARY_DIR
  "${{_libretro_cores_prefix}}/lib")
unset(_libretro_cores_prefix)
'''

CORE_PATH_HEADER = '''\
#pragma once

namespace genesis_plus_gx {{

inline constexpr char core_path[] = "{path}";

}}
'''


def main() -> None:
  if cfg.target_system() != 'Linux':
    raise SystemExit(
      f'genesis-plus-gx: only the Linux core is wired up, and this build '
      f'targets {cfg.target_system()}. Makefile.libretro has other '
      f'platforms; adding one is a platform argument here and a build '
      f'lane for that target.')
  patches = patch_files()
  tree = unpack(tarball(), patches)
  check_header(tree)
  core = place(build(tree), tree)
  cfg.emit(f'package.install/share/cmake/{PACKAGE}/genesis-plus-gx.cmake',
           CONSUMER_MODULE)
  cfg.emit('core-path.hpp', CORE_PATH_HEADER.format(path=core))
  applied = ', '.join(p.name for p in patches) or 'no patches'
  print(f'Genesis Plus GX {COMMIT[:7]} ({applied}) -> {core}')


main()
