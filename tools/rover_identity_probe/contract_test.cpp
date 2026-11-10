// Pure CDR/identity/body unit test: never creates a participant, node or client.
#define main receiver_entry_never_called
#include "observation_receiver.cpp"
#undef main
#include <cassert>
#include <iostream>
int main(){
 using namespace tfg_identity_probe;
 rt::SampleIdentity request,other;
 request.writer_guid().guidPrefix.value[0]=1;request.sequence_number().high=0;request.sequence_number().low=7;
 other=request;assert(response_for_request(request,other));
 other.sequence_number().low=8;assert(!response_for_request(request,other));
 other=request;other.writer_guid().guidPrefix.value[0]=2;assert(!response_for_request(request,other));
 assert(!response_for_request(rt::SampleIdentity::unknown(),rt::SampleIdentity::unknown()));
 ParameterType<Request>request_type("rcl_interfaces::srv::dds_::GetParameters_Request_");
 ParameterType<Response>response_type("rcl_interfaces::srv::dds_::GetParameters_Response_");
 rt::SerializedPayload_t payload(32768);Request before,after;before.names={"MAV_SYSID","DDS_USE_NS"};
 assert(request_type.serialize(&before,&payload));assert(request_type.deserialize(&payload,&after));assert(before.names==after.names);
 Response a,b;a.values.resize(2);a.values[0].type=2;a.values[0].integer_value=3;a.values[1].type=2;a.values[1].integer_value=1;
 assert(response_type.serialize(&a,&payload));assert(response_type.deserialize(&payload,&b));assert(b.values[0].integer_value==3&&b.values[1].integer_value==1);
 Sample s;Status status;status.vehicle_type=1;status.mode=15;status.armed=true;status.external_control=true;status.failsafe={21};s.message=status;
 auto data=body(s);assert(data.find("\"mode\":15")!=std::string::npos&&data.find("\"failsafe\":[21]")!=std::string::npos);
 Odometry odom;odom.header.frame_id="odom";odom.child_frame_id="base_link";odom.pose.pose.orientation.w=1.;odom.twist.twist.linear.x=.1;s.message=odom;
 data=body(s);assert(data.find("\"child_frame_id\":\"base_link\"")!=std::string::npos&&data.find("covariance")!=std::string::npos);
 std::cout<<"{\"pure_cpp_contract\":\"PASSED\",\"dds_participant_created\":false,\"ros_initialized\":false,\"movement_authorized\":false}\n";
}
