#pragma once
// Local retention credits only. No vehicle commands, authority or clock mapping.
#include <array>
#include <cstdint>
#include <stdexcept>
#include <string>
namespace tfg_identity_probe {
class PhaseSelection {
  unsigned phase_=0, credit_=0;
  std::array<bool,2> pending_{{false,false}};
  std::array<unsigned,2> count_{{0,0}};
  std::array<unsigned,6> grants_{{0,0,0,0,0,0}};
  std::array<std::int64_t,2> seen_{{-1,-1}};
public:
  static unsigned phase(char c) {
    const auto p=std::string("BIPWSD").find(c);
    if(p==std::string::npos)throw std::runtime_error("Unknown retention phase");
    return static_cast<unsigned>(p);
  }
  unsigned grant(char c) {
    const auto p=phase(c);
    if(p<phase_ || (p==phase_&&(pending_[0]||pending_[1])))
      throw std::runtime_error("Outstanding/rewound retention credit");
    const unsigned cap=p==0?1:p==1?2:p==2?4:p==3?4:3;
    if(grants_[p]>=cap || count_[0]>=10 || count_[1]>=10 ||
       (p<4&&(count_[0]>=4||count_[1]>=4)))
      throw std::runtime_error("Retention quota reserved/exhausted");
    // A forward phase cancels outstanding credit, never retained records.
    phase_=p; ++grants_[p];pending_={{true,true}};
    return ++credit_;
  }
  bool retain(unsigned topic,std::int64_t stamp) {
    if(topic>1||stamp<0)throw std::runtime_error("Invalid retention topic/stamp");
    const auto previous=seen_[topic];seen_[topic]=stamp>previous?stamp:previous;
    if(!pending_[topic]||stamp<=previous)return false;
    if(count_[topic]>=10 || (phase_<4&&count_[topic]>=4))
      throw std::runtime_error("Retention quota reserved/exhausted");
    pending_[topic]=false;++count_[topic];return true;
  }
  unsigned credit()const{return credit_;}
  char current_phase()const{return std::string("BIPWSD")[phase_];}
};
}
