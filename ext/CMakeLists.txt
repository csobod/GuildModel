cmake_minimum_required(VERSION 3.15...3.30)
project(guildmodel_stock LANGUAGES CXX)

if (NOT SKBUILD)
  message(WARNING "Build this with `pip install ./ext` from the repository root; "
                  "a bare CMake build installs nowhere useful.")
endif()

set(CMAKE_CXX_STANDARD 17)
set(CMAKE_CXX_STANDARD_REQUIRED ON)
if (NOT CMAKE_BUILD_TYPE AND NOT CMAKE_CONFIGURATION_TYPES)
  set(CMAKE_BUILD_TYPE Release CACHE STRING "Build type" FORCE)
endif()

find_package(Python 3.12 REQUIRED COMPONENTS Interpreter Development.Module)
execute_process(
  COMMAND "${Python_EXECUTABLE}" -m nanobind --cmake_dir
  OUTPUT_STRIP_TRAILING_WHITESPACE OUTPUT_VARIABLE nanobind_ROOT)
find_package(nanobind CONFIG REQUIRED)
find_package(Threads REQUIRED)

# Threads are std::thread over row bands, never OpenMP: Apple's clang ships
# none, and VTK and Qt already load runtimes of their own (§6.3).
nanobind_add_module(guildmodel_stock STABLE_ABI NB_STATIC src/stock.cpp)
target_link_libraries(guildmodel_stock PRIVATE Threads::Threads)

install(TARGETS guildmodel_stock LIBRARY DESTINATION .)
