#pragma once
#include "timing_window.hpp"
#include <string>
namespace tfg_timing {
inline std::string fields(const Window&w) {
  std::string s="\"mono_pair_ns\":["+std::to_string(w.first_mono)+","+std::to_string(w.last_mono)+
    "],\"sim_pair_ns\":["+std::to_string(w.first_sim)+","+std::to_string(w.last_sim)+"],\"spans\":[";
  for(unsigned i=0;i<4;++i){const auto&v=w.spans[i];if(i)s+=",";
    s+="["+std::to_string(v.count)+","+std::to_string(v.total)+","+std::to_string(v.maximum)+","+
      std::to_string(v.nonpositive)+","+std::to_string(v.begin)+","+std::to_string(v.end)+","+
      (i==0||i==3||!v.count||v.result==INT64_MIN?"null":std::to_string(v.result))+"]";
  }
  s+="],\"active_ns\":[";
  for(unsigned i=0;i<4;++i){if(i)s+=",";s+=std::to_string(w.active[i]);}
  return s+"],\"source_stamp_ns\":"+std::to_string(w.source_stamp_ns)+",\"incomplete\":"+(w.invalid?"true":"false");
}
}
