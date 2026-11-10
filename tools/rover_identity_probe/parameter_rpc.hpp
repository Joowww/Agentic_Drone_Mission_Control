#pragma once
// Opt-in fixed GetParameters client using PUBLIC Fast DDS + generated ROS CDR.
// No RMW private handle, replacement library, mode/arm service or controller.
#include "../rover_xrce_trace/identity_trace.hpp"
#include <rcl_interfaces/srv/get_parameters.hpp>
#include <rcl_interfaces/srv/detail/get_parameters__rosidl_typesupport_fastrtps_cpp.hpp>
#include <fastdds/dds/domain/DomainParticipantFactory.hpp>
#include <fastdds/dds/domain/DomainParticipant.hpp>
#include <fastdds/dds/publisher/Publisher.hpp>
#include <fastdds/dds/publisher/DataWriter.hpp>
#include <fastdds/dds/subscriber/Subscriber.hpp>
#include <fastdds/dds/subscriber/DataReader.hpp>
#include <fastdds/dds/subscriber/SampleInfo.hpp>
#include <fastdds/dds/topic/TypeSupport.hpp>
#include <fastdds/rtps/common/SerializedPayload.h>
#include <fastdds/rtps/common/WriteParams.h>
#include <fastcdr/FastBuffer.h>
#include <fastcdr/Cdr.h>
#include <functional>
#include <stdexcept>

namespace tfg_identity_probe {
namespace dd=eprosima::fastdds::dds;
namespace rt=eprosima::fastrtps::rtps;
namespace cdr=eprosima::fastcdr;
using Request=rcl_interfaces::srv::GetParameters_Request;
using Response=rcl_interfaces::srv::GetParameters_Response;
template<class Message>class ParameterType final:public dd::TopicDataType {
public:
 explicit ParameterType(const char*name){setName(name);m_typeSize=32768;m_isGetKeyDefined=false;}
 bool serialize(void*data,rt::SerializedPayload_t*payload)override{
  try{cdr::FastBuffer buffer(reinterpret_cast<char*>(payload->data),payload->max_size);
   cdr::Cdr stream(buffer,cdr::Cdr::DEFAULT_ENDIAN,cdr::Cdr::DDS_CDR);
   stream.serialize_encapsulation();
   if(!rcl_interfaces::srv::typesupport_fastrtps_cpp::cdr_serialize(*static_cast<Message*>(data),stream))return false;
   payload->length=stream.getSerializedDataLength();payload->encapsulation=stream.endianness()==cdr::Cdr::BIG_ENDIANNESS?CDR_BE:CDR_LE;return true;
  }catch(...){return false;}}
 bool deserialize(rt::SerializedPayload_t*payload,void*data)override{
  try{if(payload->length>32768)return false;
   cdr::FastBuffer buffer(reinterpret_cast<char*>(payload->data),payload->length);
   cdr::Cdr stream(buffer,cdr::Cdr::DEFAULT_ENDIAN,cdr::Cdr::DDS_CDR);stream.read_encapsulation();
   return rcl_interfaces::srv::typesupport_fastrtps_cpp::cdr_deserialize(stream,*static_cast<Message*>(data));
  }catch(...){return false;}}
 std::function<uint32_t()>getSerializedSizeProvider(void*data)override{
  return [data]{return static_cast<uint32_t>(rcl_interfaces::srv::typesupport_fastrtps_cpp::get_serialized_size(*static_cast<Message*>(data),0)+4);};}
 void*createData()override{return new Message;}
 void deleteData(void*data)override{delete static_cast<Message*>(data);}
 bool getKey(void*,rt::InstanceHandle_t*,bool=false)override{return false;}
};

// Shared pure rule, exercised without creating DDS participants.
inline bool response_for_request(const rt::SampleIdentity&request,const rt::SampleIdentity&related){
 return request.writer_guid()!=rt::GUID_t::unknown()&&request==related;
}

class ParameterRpc {
 dd::DomainParticipant*participant_=nullptr;dd::DataWriter*writer_=nullptr;dd::DataReader*reader_=nullptr;
 dd::TypeSupport request_type_{new ParameterType<Request>("rcl_interfaces::srv::dds_::GetParameters_Request_")};
 dd::TypeSupport response_type_{new ParameterType<Response>("rcl_interfaces::srv::dds_::GetParameters_Response_")};
 rt::SampleIdentity request_identity_;bool sent_=false,done_=false;double deadline_=0;unsigned rejected_=0;
 std::function<void(const std::string&,const std::string&)>emit_;
 static std::string id(const rt::SampleIdentity&v){return tfg_identity_trace::sample(v);}
 static void check(bool value){if(!value)throw std::runtime_error("Native RPC construction failed");}
public:
 ParameterRpc(unsigned domain,std::function<void(const std::string&,const std::string&)>emit):emit_(std::move(emit)){
  try{auto qos=dd::PARTICIPANT_QOS_DEFAULT;qos.name("tfg_v3_parameter_metadata");
   participant_=dd::DomainParticipantFactory::get_instance()->create_participant(domain,qos);check(participant_);
   check(request_type_.register_type(participant_)==eprosima::fastrtps::types::ReturnCode_t::RETCODE_OK);check(response_type_.register_type(participant_)==eprosima::fastrtps::types::ReturnCode_t::RETCODE_OK);
   auto*pub=participant_->create_publisher(dd::PUBLISHER_QOS_DEFAULT);auto*sub=participant_->create_subscriber(dd::SUBSCRIBER_QOS_DEFAULT);check(pub&&sub);
   auto*rq=participant_->create_topic("rq/ap/v3/get_parametersRequest",request_type_.get_type_name(),dd::TOPIC_QOS_DEFAULT);
   auto*rr=participant_->create_topic("rr/ap/v3/get_parametersReply",response_type_.get_type_name(),dd::TOPIC_QOS_DEFAULT);check(rq&&rr);
   auto wq=dd::DATAWRITER_QOS_DEFAULT;wq.reliability().kind=dd::RELIABLE_RELIABILITY_QOS;wq.history().depth=10;
   auto rqos=dd::DATAREADER_QOS_DEFAULT;rqos.reliability().kind=dd::RELIABLE_RELIABILITY_QOS;rqos.history().depth=10;
   writer_=pub->create_datawriter(rq,wq);reader_=sub->create_datareader(rr,rqos);check(writer_&&reader_);
  }catch(...){close();throw;}}
 void poll(double now){
  if(done_)return;
  if(!sent_){
   dd::PublicationMatchedStatus match;if(writer_->get_publication_matched_status(match)!=eprosima::fastrtps::types::ReturnCode_t::RETCODE_OK||match.current_count<1)return;
   Request request;request.names={"MAV_SYSID","DDS_USE_NS"};rt::WriteParams params;
   // Same public Fast DDS request convention as the installed RMW: a related
   // reader GUID is a return endpoint, NOT the request writer identity.
   params.related_sample_identity().writer_guid(reader_->guid());
   const auto send_started=std::chrono::duration_cast<std::chrono::nanoseconds>(std::chrono::steady_clock::now().time_since_epoch()).count();
   const bool accepted=writer_->write(&request,params);sent_=true;deadline_=now+2.;
   request_identity_=params.sample_identity();
   emit_("rpc_request","\"metadata_source\":\"FASTDDS_WRITE_PARAMS\",\"sent_steady_ns\":"+std::to_string(send_started)+",\"request_identity\":"+id(request_identity_)+
    ",\"request_writer_guid\":"+tfg_xrce_trace::quote(tfg_identity_trace::guid(writer_->guid()))+
    ",\"reply_reader_guid\":"+tfg_xrce_trace::quote(tfg_identity_trace::guid(reader_->guid()))+
    ",\"accepted\":"+(accepted?"true":"false"));
   if(!accepted){done_=true;throw std::runtime_error("Native RPC send unconfirmed");}
  }
  Response response;dd::SampleInfo info;
  if(reader_->take_next_sample(&response,&info)==eprosima::fastrtps::types::ReturnCode_t::RETCODE_OK){
   if(!info.valid_data||!response_for_request(request_identity_,info.related_sample_identity)){
    if(++rejected_>8)throw std::runtime_error("Native RPC unrelated response budget");
    return;}
   done_=true;
   std::string values="{\"MAV_SYSID\":null,\"DDS_USE_NS\":null}";
   if(response.values.size()==2&&response.values[0].type==2&&response.values[1].type==2)
    values="{\"MAV_SYSID\":"+std::to_string(response.values[0].integer_value)+",\"DDS_USE_NS\":"+std::to_string(response.values[1].integer_value)+"}";
   const auto received=std::chrono::duration_cast<std::chrono::nanoseconds>(std::chrono::steady_clock::now().time_since_epoch()).count();
   emit_("rpc_reply","\"metadata_source\":\"FASTDDS_SAMPLE_INFO\",\"received_steady_ns\":"+std::to_string(received)+",\"request_identity\":"+id(request_identity_)+
    ",\"sample_identity\":"+id(info.sample_identity)+",\"related_identity\":"+id(info.related_sample_identity)+
    ",\"values\":"+values+",\"value_attribution\":\"UNVERIFIED_UNTIL_NATIVE_XRCE_JOIN\"");
  }else if(now>=deadline_){done_=true;emit_("rpc_timeout","\"reason\":\"RESPONSE_DEADLINE\"");}
 }
 void close(){if(participant_){auto*p=participant_;participant_=nullptr;
   check(p->delete_contained_entities()==eprosima::fastrtps::types::ReturnCode_t::RETCODE_OK);
   check(dd::DomainParticipantFactory::get_instance()->delete_participant(p)==eprosima::fastrtps::types::ReturnCode_t::RETCODE_OK);}}
 ~ParameterRpc(){try{close();}catch(...) {}}
 ParameterRpc(const ParameterRpc&)=delete;ParameterRpc&operator=(const ParameterRpc&)=delete;
};
}
