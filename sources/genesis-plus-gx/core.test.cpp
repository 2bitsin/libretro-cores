#include <dlfcn.h>

#include <cstddef>
#include <iostream>
#include <string>
#include <vector>

#include <gtest/gtest.h>

#include "core-path.hpp"
#include "libretro.h"

namespace {

class Core {
 public:
  Core() : handle_(dlopen(genesis_plus_gx::core_path, RTLD_NOW | RTLD_LOCAL)),
           error_(handle_ ? "" : dlerror()) {}
  ~Core() {
    if (handle_) {
      dlclose(handle_);
    }
  }

  Core(const Core&) = delete;
  Core& operator=(const Core&) = delete;

  const std::string& error() const { return error_; }

  template <typename Fn>
  Fn symbol(const char* name) const {
    return reinterpret_cast<Fn>(dlsym(handle_, name));
  }

 private:
  void* handle_;
  std::string error_;
};

// The pinned tree writes 81315 bytes with no game loaded; patches/0001 adds
// the 69 byte gamepad context, patches/0002 nothing, its block being Mega
// Drive only, and patches/0003 the four byte FM BUSY end cycle.
constexpr std::size_t kPayloadBytes = 81388;

bool NoEnvironmentSupport(unsigned command, void* data) {
  (void)data;
  return (command & 0xffff) == RETRO_ENVIRONMENT_SET_PIXEL_FORMAT;
}

// state_save writes a prefix of the caller's buffer and reports its length
// to nobody, so serialize the same state into two differently filled
// buffers: they agree wherever it wrote and nowhere else.
std::size_t PayloadBytes(const Core& core) {
  const std::size_t total =
      core.symbol<std::size_t (*)()>("retro_serialize_size")();
  std::vector<unsigned char> written(total, 0xaa), again(total, 0x55);
  const auto serialize =
      core.symbol<bool (*)(void*, std::size_t)>("retro_serialize");
  if (!serialize(written.data(), total) || !serialize(again.data(), total)) {
    return 0;
  }
  for (std::size_t at = total; at-- > 0;) {
    if (written[at] == again[at]) {
      return at + 1;
    }
  }
  return 0;
}

TEST(GenesisPlusGx, SpeaksLibretroApiVersionOne) {
  const Core core;
  ASSERT_TRUE(core.error().empty()) << core.error();

  const auto api_version = core.symbol<unsigned (*)()>("retro_api_version");
  ASSERT_NE(api_version, nullptr) << "retro_api_version is not exported";
  EXPECT_EQ(api_version(), RETRO_API_VERSION);
}

TEST(GenesisPlusGx, ReportsItsIdentity) {
  const Core core;
  ASSERT_TRUE(core.error().empty()) << core.error();

  const auto system_info =
      core.symbol<void (*)(retro_system_info*)>("retro_get_system_info");
  ASSERT_NE(system_info, nullptr) << "retro_get_system_info is not exported";

  retro_system_info info{};
  system_info(&info);
  ASSERT_NE(info.library_name, nullptr);
  ASSERT_NE(info.library_version, nullptr);
  std::cout << info.library_name << ' ' << info.library_version << '\n';

  EXPECT_STREQ(info.library_name, "Genesis Plus GX");
  EXPECT_TRUE(std::string(info.library_version).starts_with("v1.7.4"));
}

TEST(GenesisPlusGx, SaveStatesCarryEveryPatchedField) {
  const Core core;
  ASSERT_TRUE(core.error().empty()) << core.error();

  core.symbol<void (*)(retro_environment_t)>("retro_set_environment")(
      NoEnvironmentSupport);
  core.symbol<void (*)()>("retro_init")();
  const std::size_t payload = PayloadBytes(core);
  core.symbol<void (*)()>("retro_deinit")();

  EXPECT_EQ(payload, kPayloadBytes);
}

}  // namespace
