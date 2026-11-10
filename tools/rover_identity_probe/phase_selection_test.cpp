#include "phase_selection.hpp"
#include <cassert>
#include <iostream>
using tfg_identity_probe::PhaseSelection;
template<class F>void rejects(F f){bool failed=false;try{f();}catch(const std::exception&){failed=true;}assert(failed);}
int main(){
 PhaseSelection s;
 assert(!s.retain(0,10));assert(!s.retain(1,10)); // idle cannot spend future quota
 auto pair=[&](char p,int stamp){s.grant(p);assert(s.retain(0,stamp));assert(!s.retain(0,stamp));assert(s.retain(1,stamp));};
 pair('B',11);pair('I',12);pair('P',13);pair('P',14);
 rejects([&]{s.grant('P');});rejects([&]{s.grant('W');}); // six reserved pairs
 pair('S',15);pair('S',16);pair('S',17);
 pair('D',18);pair('D',19);pair('D',20);rejects([&]{s.grant('D');});
 PhaseSelection loss;loss.grant('B');assert(loss.retain(0,1));rejects([&]{loss.grant('B');});
 loss.grant('S');assert(loss.retain(0,2));assert(loss.retain(1,2));rejects([&]{loss.grant('W');});
 PhaseSelection progressive;progressive.grant('B');assert(progressive.retain(0,100));assert(progressive.retain(1,100));
 assert(!progressive.retain(0,200));progressive.grant('I');assert(!progressive.retain(0,150));assert(!progressive.retain(0,200));assert(progressive.retain(0,201));
 rejects([&]{progressive.grant('X');});
 std::cout<<"{\"phase_selection_contract\":\"PASSED\",\"ros_initialized\":false,\"dds_participant_created\":false}\n";
}
