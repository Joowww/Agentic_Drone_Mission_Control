#pragma once
// Pure bounded counters. No middleware, allocations, exception syntax or clocks
// substituted for the caller's simulation clock. Durations are MONOTONIC only.
#include <stdint.h>
#include <time.h>
#include <errno.h>
namespace tfg_timing {
inline uint64_t now() noexcept {
  int saved=errno;timespec t{};const bool ok=clock_gettime(CLOCK_MONOTONIC,&t)==0;errno=saved;
  return ok?uint64_t(t.tv_sec)*1000000000ULL+uint64_t(t.tv_nsec):0;
}
struct Span {
  uint64_t count=0,total=0,maximum=0,nonpositive=0,begin=0,end=0;
  int64_t result=0;
  void add(uint64_t a,uint64_t b,int64_t r) noexcept {
    if(!a||b<a)return;
    ++count;total+=b-a;if(b-a>maximum)maximum=b-a;
    if(r<=0){++nonpositive;}
    begin=a;end=b;result=r;
  }
};
struct Window {
  uint64_t first_mono=0,last_mono=0,first_sim=0,last_sim=0,emitted=0;
  Span spans[4];bool invalid=false;
  uint64_t active[4]{};int64_t source_stamp_ns=-1;
  void observe(uint64_t sim,uint64_t mono) noexcept {
    if(!mono||(last_mono&&(mono<last_mono||sim<last_sim)))invalid=true;
    if(!first_mono){first_mono=mono;first_sim=sim;}
    last_mono=mono;last_sim=sim;
  }
  bool due() noexcept {
    if(!first_mono||last_mono-first_mono<1000000000ULL)return false;
    if(emitted&&last_mono-emitted<10000000000ULL)return false;
    emitted=last_mono;return true;
  }
};
}
