"""Conan recipe: the requires come from sources/CMakeLists.txt's Require()
calls, the package kind from buildutil.toml's [package] section."""

from __future__ import annotations

import os
import re
from pathlib import Path

from conan import ConanFile
from conan.tools.cmake import CMakeDeps, CMakeToolchain, cmake_layout


def _package_section() -> dict:
  """[package] from buildutil.toml beside this file; {} = consumer-only."""
  toml = Path(__file__).resolve().parent / "buildutil.toml"
  if not toml.is_file():
    return {}
  import tomllib
  section = tomllib.loads(toml.read_text(encoding="utf-8")).get("package", {})
  return section if section.get("kind") in ("library", "application") else {}


_PKG = _package_section()


REQUIRE_RE = re.compile(
  # Package names are not \w-only (yaml-cpp).
  r'^\s*Require\s*\(\s*([\w-]+)\s+VERSION\s+"([^"]+)"(.*?)\)',
  re.MULTILINE | re.DOTALL,
)


_KEYWORDS = {"TEST", "BENCH", "TOOL", "SYSTEM", "CONAN", "COMPONENTS",
             "PLATFORM", "OPTIONS", "PUBLIC"}


def _coerce_option(value: str):
  """Conan option values as their natural types."""
  if value in ("True", "False"):
    return value == "True"
  try:
    return int(value)
  except ValueError:
    return value


def _parse_extra(extra: str) -> dict:
  tokens = extra.replace("\n", " ").split()
  out = {"test": False, "bench": False, "tool": False, "system": False,
         "public": False, "conan": None, "components": [], "platform": [],
         "options": {}}
  sugar = []
  i = 0
  while i < len(tokens):
    # Exact case, as cmake_parse_arguments does it: a lowercase `system`
    # is a value (Boost's component), not the SYSTEM keyword.
    t = tokens[i]
    if t == "TEST":
      out["test"] = True
      i += 1
    elif t == "SYSTEM":
      out["system"] = True
      i += 1
    elif t == "BENCH":
      out["bench"] = True
      i += 1
    elif t == "TOOL":
      out["tool"] = True
      i += 1
    elif t == "PUBLIC":
      out["public"] = True
      i += 1
    elif t == "CONAN":
      out["conan"] = tokens[i + 1]
      i += 2
    elif t == "COMPONENTS":
      i += 1
      while i < len(tokens) and tokens[i] not in _KEYWORDS:
        # Shorthand is collected, not applied: an OPTIONS keyword may
        # follow the components on the same call.
        if tokens[i][:1] in ("+", "-"):
          sugar.append(tokens[i])
        else:
          out["components"].append(tokens[i])
        i += 1
    elif t == "PLATFORM":
      i += 1
      while i < len(tokens) and tokens[i] not in _KEYWORDS:
        out["platform"].append(tokens[i])
        i += 1
    elif t == "OPTIONS":
      i += 1
      while i < len(tokens) and tokens[i] not in _KEYWORDS:
        key, eq, value = tokens[i].partition("=")
        if not eq or not key:
          raise ValueError(
            f"Require OPTIONS token {tokens[i]!r} is not key=value")
        out["options"][key] = _coerce_option(value)
        i += 1
    else:
      i += 1
  _apply_sugar(out, sugar)
  return out


def _apply_sugar(out: dict, sugar: list) -> None:
  """COMPONENTS tokens written +name / -name, as the options they mean:
  `+asio` is `with_asio=True`, `-json` is `without_json=True`."""
  signs = {}
  for token in sugar:
    sign, name = token[0], token[1:]
    if not name:
      raise ValueError(
        f"Require COMPONENTS token {token!r} names no option")
    if signs.setdefault(name, sign) != sign:
      raise ValueError(
        f"Require COMPONENTS has both '+{name}' and '-{name}'")
    for spelling in (f"with_{name}", f"without_{name}"):
      if spelling in out["options"]:
        raise ValueError(
          f"Require COMPONENTS {token!r} and OPTIONS "
          f"{spelling}={out['options'][spelling]!r} both set an option "
          f"for {name!r}")
    out["options"]["with_" + name if sign == "+" else "without_" + name] = True
  if sugar and out["system"]:
    raise ValueError(
      "Require COMPONENTS option shorthand with SYSTEM is meaningless — "
      "a SYSTEM dep is the host's package and conan never builds it")


def _to_conan_version(v: str) -> str:
  v = v.strip()
  if v == "*":
    return "[*]"
  ops = (">=", "<=", ">", "<", "~", "^")
  if not any(v.startswith(op) for op in ops):
    return v
  # Capped at (major+1): non-semver recipe versions like "cci.20210126"
  # sort lexically above real releases.
  m = re.match(r"^[><=~^]+\s*(\d+)\.", v)
  if m:
    major = int(m.group(1))
    return f"[{v} <{major + 1}]"
  return f"[{v}]"


def _parse_requires(recipe_folder: Path, target_os: str) -> list[dict]:
  text = (recipe_folder / "sources" / "CMakeLists.txt").read_text()
  entries = []
  for name, version, extra in REQUIRE_RE.findall(text):
    info = _parse_extra(extra)
    # An empty PLATFORM list means all platforms.
    if info["platform"] and target_os not in info["platform"]:
      continue
    # SYSTEM is the host's package: find_package only, no graph entry.
    if info["system"]:
      continue
    entries.append({
      "conan_name": info["conan"] or name.lower(),
      "version": _to_conan_version(version),
      "test":  info["test"],
      "bench": info["bench"],
      "tool":  info["tool"],
      "public": info["public"],
      "options": info["options"],
    })
  return entries


class ProjectRecipe(ConanFile):
  name = _PKG.get("name", "libretro-cores")
  settings = "os", "compiler", "build_type", "arch"
  if _PKG:
    package_type = {"library": "library",
                    "application": "application"}[_PKG["kind"]]
    if _PKG["kind"] == "library":
      # The driver passes -o &:shared=True when module_linkage says shared.
      options = {"shared": [True, False]}
      default_options = {"shared": False}
    # exports ride with the recipe into the cache and are readable at graph
    # time; exports_sources only materialize for a build.
    exports = ("buildutil.toml", "sources/CMakeLists.txt")
    # conan hashes the exported files into the recipe revision, so a
    # generated file present on one machine and not another splits a
    # release across two revisions and hides the binaries under the other.
    exports_sources = ("CMakeLists.txt", "buildutil.toml", "sources/*",
                       "cmake/*", ".buildutil/*",
                       "!sources/**/cmake_test_discovery_*.json",
                       "!sources/**/__pycache__/**",
                       "!sources/**/*.pyc")

  def set_version(self):
    # The driver computes the version and passes --version; 0.0.0 is the
    # consumer-only placeholder nothing ever publishes.
    self.version = self.version or "0.0.0"

  def validate(self):
    # buildutil exports BUILDUTIL=<version> to every child it drives.
    if not os.environ.get("BUILDUTIL"):
      from conan.errors import ConanInvalidConfiguration
      raise ConanInvalidConfiguration(
        "this project is controlled by buildutil — run `buildutil build` "
        "(conan is orchestrated: profile, CONAN_HOME and the dependency "
        "graph all come from the driver). If you really need direct "
        "conan, set BUILDUTIL=1 in the environment.")

  def package_id(self):
    # The cores come out of their own makefiles, never the consumer's
    # toolchain, so only os and arch change the bytes.
    del self.info.settings.compiler
    del self.info.settings.build_type
    self.info.options.rm_safe("shared")

  def layout(self):
    cmake_layout(self)
    profile = _profile_name(self.settings)
    self.folders.build = f"_build/{profile}"
    self.folders.generators = f"_build/{profile}/generators"

  def generate(self):
    CMakeToolchain(self).generate()
    CMakeDeps(self).generate()

  def requirements(self):
    target_os = str(self.settings.os)
    for entry in _parse_requires(Path(self.recipe_folder), target_os):
      if entry["tool"]:
        continue                       # build_requirements() owns these
      ref = f"{entry['conan_name']}/{entry['version']}"
      # On the requires call rather than default_options, so the option
      # follows the entry's own gating.
      kwargs = {"options": entry["options"]} if entry["options"] else {}
      # conan does not propagate a static-lib requirement's headers by
      # default, and a PUBLIC dep's headers are in ours.
      if entry["public"]:
        kwargs["transitive_headers"] = True
      # conan has no bench_requires; BENCH has TEST's semantics anyway.
      if entry["test"] or entry["bench"]:
        if os.environ.get("LIBRETRO_SKIP_TEST_DEPS") != "1":
          self.test_requires(ref, **kwargs)   # --no-tests drops these
      else:
        self.requires(ref, **kwargs)

  def build_requirements(self):
    target_os = str(self.settings.os)
    for entry in _parse_requires(Path(self.recipe_folder), target_os):
      if entry["tool"]:
        kwargs = {"options": entry["options"]} if entry["options"] else {}
        self.tool_requires(
          f"{entry['conan_name']}/{entry['version']}", **kwargs)

  def build(self):
    if not _PKG:
      return
    import sys
    # Folders may be unset on a barely-constructed recipe, and the refusal
    # below must fire rather than an AttributeError.
    source = Path(getattr(self, "source_folder", None)
                  or getattr(self, "recipe_folder", None) or ".")
    vendored = source / ".buildutil"
    if (vendored / "buildutil" / "__main__.py").is_file():
      # The baked lane: conan has resolved the graph and generated the
      # toolchain, so cache-build only runs cmake -- no venv, no network.
      shared = self.options.get_safe("shared")
      toolchain = Path(self.generators_folder) / "conan_toolchain.cmake"
      previous = os.environ.get("PYTHONPATH")
      os.environ["PYTHONPATH"] = (
        f"{vendored}{os.pathsep}{previous}" if previous else str(vendored))
      try:
        self.run(
          f'"{sys.executable}" -m buildutil cache-build'
          f' --build-dir "{self.build_folder}"'
          f' --toolchain "{toolchain}"'
          f' --build-type {self.settings.build_type}'
          f' --linkage {"shared" if shared else "static"}',
          cwd=str(source))
      finally:
        if previous is None:
          os.environ.pop("PYTHONPATH", None)
        else:
          os.environ["PYTHONPATH"] = previous
      return
    from conan.errors import ConanException
    # settings is still the class-level tuple until conan populates it.
    version = getattr(self, "version", None)
    ref = f"{self.name}/{version}" if version else self.name
    settings = getattr(self, "settings", None)
    def _setting(name):
      return settings.get_safe(name) if hasattr(settings, "get_safe") else "?"
    profile = (f"build_type={_setting('build_type')}, "
               f"compiler={_setting('compiler')}-{_setting('compiler.version')}, "
               f"cppstd={_setting('compiler.cppstd')}")
    raise ConanException(
      f"{self.name}: building this package from source inside the conan "
      "cache is not supported — it was published WITHOUT its build "
      "driver baked in (`buildutil publish --bake-buildutil` changes "
      "that), so binaries come from the project remote, which publish "
      "keeps populated. Fetch a prebuilt binary, or clone the project "
      "and run `buildutil publish` for your profile.\n"
      f"You are here because no published binary matched your profile: "
      f"{profile}.\n"
      "SEE WHAT IS ACTUALLY PUBLISHED FIRST — it settles this in one "
      f"command:\n    conan list \"{ref}:*\" -r <remote>\n"
      "If the published list simply has no entry for your build_type "
      "(publishing Release but not Debug, or the reverse, is the common "
      "case), the fix is on the PUBLISHER: run `buildutil publish` for "
      "the missing profile. Nothing is wrong on your side.\n"
      "Only if your build_type IS published does the package_id-drift "
      "explanation apply: a version-RANGED dependency of this "
      "package resolved differently in your cache than at publish time. "
      "Compare `conan graph info` resolutions against the published "
      "package's requires and align them (update/pin the drifting dep) "
      "instead of building from source.")

  def package(self):
    if not _PKG:
      return
    # build_folder is the tree buildutil just built; install it whole.
    self.run(f'cmake --install "{self.build_folder}" '
             f'--prefix "{self.package_folder}"')
    # The source mirror puts a top-level module's own artifacts at the
    # package root: here that is an empty archive and the test binary.
    root = Path(self.package_folder)
    for stale in (*root.glob("*.a"), *root.glob("*-tests"),
                  *root.glob("*-benches")):
      stale.unlink()

  def package_info(self):
    if not _PKG:
      return
    # Nothing here is linkable: every libretro core exports the same retro_*
    # symbols, so a consumer could link at most one and would still have to
    # dlopen the rest by path.
    self.cpp_info.libs = []
    self.cpp_info.bindirs = []
    self.cpp_info.libdirs = ["lib"]
    self.cpp_info.includedirs = ["include"]
    module_dir = os.path.join("share", "cmake", self.name)
    self.cpp_info.builddirs = [module_dir]
    self.cpp_info.set_property("cmake_build_modules", [
      os.path.join(module_dir, f.name)
      for f in sorted((Path(self.package_folder) / module_dir).glob("*.cmake"))
    ])
    self.runenv_info.define_path(
      "LIBRETRO_CORES_DIR", os.path.join(self.package_folder, "lib"))


def _module_linkage() -> str:
  """The module_linkage option, resolved as the driver resolves it: env,
  then the checkout-local ini, then static.  layout() needs it because
  static and shared are separate build trees."""
  env = os.environ.get("BUILDUTIL_OPT_MODULE_LINKAGE", "")
  if env in ("static", "shared"):
    return env
  ini = Path(__file__).resolve().parent / "_bdudata" / "config.ini"
  if ini.is_file():
    section = ""
    for raw in ini.read_text().splitlines():
      line = raw.split("#", 1)[0].strip()
      if not line:
        continue
      if line.startswith("[") and line.endswith("]"):
        section = line[1:-1].strip().lower()
      elif section == "options":
        key, _, value = line.partition("=")
        if key.strip() == "module_linkage" and value.strip() in (
            "static", "shared"):
          return value.strip()
  return "static"


def _profile_name(settings) -> str:
  parts = [str(settings.arch), str(settings.os), str(settings.compiler)]
  linkage = _module_linkage()
  if linkage != "static":
    parts.append(linkage)
  parts.append(str(settings.build_type))
  return "-".join(parts).lower()
