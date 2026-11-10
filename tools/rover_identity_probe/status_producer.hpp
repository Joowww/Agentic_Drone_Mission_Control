#pragma once
#include "timing_window.hpp"
// No allocation, exception syntax or diagnostic implementation in ArduPilot TUs.
// Definitions are linked from one isolated, exception-enabled diagnostic object.
namespace tfg_status {
class Producer {
public:
  static long long now() noexcept;
  static void loop_enter() noexcept;
  static void clock(unsigned long long,long long,long long) noexcept;
  static void check(unsigned long long,unsigned long long,unsigned) noexcept;
  static void evaluate(unsigned long long,unsigned long long,bool,bool,long long,long long) noexcept;
  static void stamp(const char*,long long,unsigned) noexcept;
  static void stream_enter(unsigned) noexcept;
  static void stream_return(unsigned) noexcept;
  static void serialized(bool) noexcept;
  static bool timing_active() noexcept;
  static void json_timing(tfg_timing::Window&) noexcept;
};
}
