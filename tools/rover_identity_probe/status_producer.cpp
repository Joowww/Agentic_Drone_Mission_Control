#include "status_producer.hpp"
#include "status_producer_impl.hpp"
namespace tfg_status {
long long Producer::now() noexcept {return ProducerImplementation::now();}
void Producer::loop_enter() noexcept {ProducerImplementation::loop_enter();}
void Producer::clock(unsigned long long a,long long b,long long c) noexcept {ProducerImplementation::clock(a,b,c);}
void Producer::check(unsigned long long a,unsigned long long b,unsigned c) noexcept {ProducerImplementation::check(a,b,c);}
void Producer::evaluate(unsigned long long a,unsigned long long b,bool c,bool d,long long e,long long f) noexcept {ProducerImplementation::evaluate(a,b,c,d,e,f);}
void Producer::stamp(const char*a,long long b,unsigned c) noexcept {ProducerImplementation::stamp(a,b,c);}
void Producer::stream_enter(unsigned a) noexcept {ProducerImplementation::stream_enter(a);}
void Producer::stream_return(unsigned a) noexcept {ProducerImplementation::stream_return(a);}
void Producer::serialized(bool a) noexcept {ProducerImplementation::serialized(a);}
bool Producer::timing_active() noexcept {return ProducerImplementation::timing_active();}
void Producer::json_timing(tfg_timing::Window&w) noexcept {ProducerImplementation::json_timing(w);}
}
