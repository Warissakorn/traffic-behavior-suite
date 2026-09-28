cmake_minimum_required(VERSION 3.24)
project(tbs_engine VERSION 0.0.1 LANGUAGES CXX)

set(CMAKE_CXX_STANDARD 20)
set(CMAKE_CXX_STANDARD_REQUIRED ON)

option(TBS_WITH_TENSORRT "Build TensorRT backend" ON)
option(TBS_WITH_NVDEC    "Build NVDEC video decoder" ON)
option(TBS_BUILD_TESTS   "Build unit tests" ON)

# Dependencies (vcpkg): OpenCV, Eigen3, Arrow/Parquet, yaml-cpp, spdlog, GTest
# Sources are added per stage as they are ported from the Python reference
# (see docs/SPEC.md §5 and docs/ROADMAP.md phase 4).
