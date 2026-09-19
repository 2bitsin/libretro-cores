cmake_minimum_required(VERSION 3.25)
project(package_smoke CXX)

find_package(libretro-cores REQUIRED CONFIG)

if(NOT EXISTS "${LIBRETRO_CORES_GENESIS_PLUS_GX}")
  message(FATAL_ERROR
    "find_package(libretro-cores) named no core to load: "
    "LIBRETRO_CORES_GENESIS_PLUS_GX=${LIBRETRO_CORES_GENESIS_PLUS_GX}")
endif()

get_property(runtime_dir GLOBAL PROPERTY LIBRETRO_CORES_RUNTIME_LIBRARY_DIR)
if(NOT IS_DIRECTORY "${runtime_dir}")
  message(FATAL_ERROR
    "libretro-cores publishes no runtime payload: "
    "LIBRETRO_CORES_RUNTIME_LIBRARY_DIR=${runtime_dir}")
endif()

add_executable(smoke smoke.cpp)
target_compile_definitions(smoke PRIVATE
  GENESIS_PLUS_GX_CORE="${LIBRETRO_CORES_GENESIS_PLUS_GX}")
target_link_libraries(smoke PRIVATE libretro-cores::libretro-cores)
