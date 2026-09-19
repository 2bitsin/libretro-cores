// A consumer of the package: the core path comes from find_package, the
// header from the package's include dir, and nothing is linked.
#include <dlfcn.h>

#include <cstdio>
#include <cstring>

#include <genesis-plus-gx/libretro.h>

namespace {

template <typename Fn>
Fn symbol(void* core, const char* name) {
  return reinterpret_cast<Fn>(dlsym(core, name));
}

}  // namespace

int main() {
  void* core = dlopen(GENESIS_PLUS_GX_CORE, RTLD_NOW | RTLD_LOCAL);
  if (!core) {
    std::fprintf(stderr, "dlopen(%s): %s\n", GENESIS_PLUS_GX_CORE, dlerror());
    return 1;
  }

  const auto api_version = symbol<unsigned (*)()>(core, "retro_api_version");
  const auto system_info =
      symbol<void (*)(retro_system_info*)>(core, "retro_get_system_info");
  if (!api_version || !system_info) {
    std::fprintf(stderr, "%s exports no libretro entry points\n",
                 GENESIS_PLUS_GX_CORE);
    return 1;
  }
  if (api_version() != RETRO_API_VERSION) {
    std::fprintf(stderr, "libretro api %u, expected %u\n", api_version(),
                 RETRO_API_VERSION);
    return 1;
  }

  retro_system_info info{};
  system_info(&info);
  std::printf("%s %s\n", info.library_name, info.library_version);
  return std::strcmp(info.library_name, "Genesis Plus GX") == 0 ? 0 : 1;
}
