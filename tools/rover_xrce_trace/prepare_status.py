"""Frozen-source Status hooks. File copies only; no build/install/SDK access."""
import difflib
import hashlib
import json
from pathlib import Path
import shutil

from .prepare import prepare, replace_once

AP_CLIENT_SHA256 = 'f512901b5c3617aa46861a967ef1cddb2515878523b1fbf240bbb54333ceaef4'
PROJECT = Path(__file__).resolve().parents[2]


def patch_ap(text):
    if hashlib.sha256(text.encode()).hexdigest() != AP_CLIENT_SHA256:
        raise ValueError('AP_DDS source differs from reviewed source; no guessed anchors')
    # These board macros are defined by the build's forced ap_config.h include.
    text = '#include <AP_HAL/AP_HAL_Boards.h>\n#if CONFIG_HAL_BOARD == HAL_BOARD_SITL\n#include "status_producer.hpp"\n#define TFG_STATUS(call) tfg_status::Producer::call\n#define TFG_STATUS_NOW() tfg_status::Producer::now()\n#else\n#define TFG_STATUS(call) do {} while (0)\n#define TFG_STATUS_NOW() 0\n#endif\n' + text
    begin = text.index('void AP_DDS_Client::update_topic(builtin_interfaces_msg_Time& msg)')
    end = text.index('#endif // AP_DDS_TIME_PUB_ENABLED', begin)
    body = text[begin:end]
    body = replace_once(body, '        return;', '        TFG_STATUS(stamp("EXTERNAL_CLOCK", msg.sec, msg.nanosec));\n        return;')
    body = replace_once(body, '    uint64_t utc_usec;', '    uint64_t utc_usec;\n    bool diagnostic_ap_clock = false;')
    body = replace_once(body, '        utc_usec = AP_HAL::micros64();', '        utc_usec = AP_HAL::micros64();\n        diagnostic_ap_clock = true;')
    body = replace_once(body, '    msg.nanosec = (utc_usec % 1000000ULL) * 1000UL;',
        '    msg.nanosec = (utc_usec % 1000000ULL) * 1000UL;\n    TFG_STATUS(stamp(diagnostic_ap_clock ? "AP_HAL" : "RTC", msg.sec, msg.nanosec));\n    (void)diagnostic_ap_clock;')
    text = text[:begin]+body+text[end:]
    begin = text.index('bool AP_DDS_Client::update_topic(ardupilot_msgs_msg_Status& msg)')
    end = text.index('#endif // AP_DDS_STATUS_PUB_ENABLED', begin)
    body = replace_once(text[begin:end], '    const auto timestamp = AP_HAL::millis64();',
        '    const auto diagnostic_read_start = TFG_STATUS_NOW();\n    const auto timestamp = AP_HAL::millis64();\n    TFG_STATUS(evaluate(timestamp, last_status_publish_time_ms, is_message_changed, connected, diagnostic_read_start, TFG_STATUS_NOW()));\n    (void)diagnostic_read_start;')
    text = text[:begin]+body+text[end:]
    begin = text.index('void AP_DDS_Client::write_status_topic()')
    end = text.index('#endif // AP_DDS_STATUS_PUB_ENABLED', begin)
    body = replace_once(text[begin:end], '        uxr_prepare_output_stream(',
        '        TFG_STATUS(stream_enter(topics[to_underlying(TopicIndex::STATUS_PUB)].dw_id.id));\n        const uint16_t diagnostic_request_id = uxr_prepare_output_stream(')
    body = replace_once(body, '        const bool success =',
        '        TFG_STATUS(stream_return(diagnostic_request_id));\n        (void)diagnostic_request_id;\n        const bool success =')
    body = replace_once(body, '        if (!success) {',
        '        TFG_STATUS(serialized(success));\n        if (!success) {')
    text = text[:begin]+body+text[end:]
    text = replace_once(text, 'void AP_DDS_Client::update()\n{\n    WITH_SEMAPHORE(csem);',
        'void AP_DDS_Client::update()\n{\n    TFG_STATUS(loop_enter());\n    WITH_SEMAPHORE(csem);')
    text = replace_once(text, 'void AP_DDS_Client::update()\n{\n    TFG_STATUS(loop_enter());\n    WITH_SEMAPHORE(csem);\n    const auto cur_time_ms = AP_HAL::millis64();',
        'void AP_DDS_Client::update()\n{\n    TFG_STATUS(loop_enter());\n    WITH_SEMAPHORE(csem);\n    const auto diagnostic_read_start = TFG_STATUS_NOW();\n    const auto cur_time_ms = AP_HAL::millis64();\n    TFG_STATUS(clock(cur_time_ms, diagnostic_read_start, TFG_STATUS_NOW()));\n    (void)diagnostic_read_start;')
    return replace_once(text, '    if (cur_time_ms - last_status_check_time_ms > DELAY_STATUS_TOPIC_MS) {',
        '    if (cur_time_ms - last_status_check_time_ms > DELAY_STATUS_TOPIC_MS) {\n        TFG_STATUS(check(cur_time_ms, last_status_check_time_ms, DELAY_STATUS_TOPIC_MS));')


def patch_agent(text):
    old = 'bool FastDDSDataWriter::write(const std::vector<uint8_t>& data)\n{\n    return ptr_->write(&const_cast<std::vector<uint8_t>&>(data));\n}'
    new = '''bool FastDDSDataWriter::write(const std::vector<uint8_t>& data)
{
    bool diagnostic_status = false;
    unsigned long long diagnostic_write_id = 0;
    try {
        diagnostic_status = std::getenv("TFG_STATUS_DIAGNOSTIC") &&
            std::string(ptr_->get_topic()->get_name()) == "rt/ap/v3/status";
        if (diagnostic_status) {
            auto& diagnostic = tfg_status::Diagnostic::instance("agent");
            diagnostic.poll_markers();
            if (diagnostic.requested()) {
                static std::atomic<unsigned long long> writes{0};
                diagnostic_write_id = ++writes;
                const auto& guid = ptr_->guid();
                std::string payload;
                if (data.size() <= 128) payload = ",\\\\"cdr_hex\\\\":\\\\"" + tfg_xrce_trace::hex(data.data(),data.size()) + "\\\\"";
                else payload = ",\\\\"payload_state\\\\":\\\\"OMITTED_BOUND_EXCEEDED\\\\"";
                diagnostic.emit("status_dds_write_enter", "\\\\"write_id\\\\":" + std::to_string(diagnostic_write_id) + ",\\\\"native_guid\\\\":\\\\"" +
                    tfg_xrce_trace::hex(guid.guidPrefix.value,12) + tfg_xrce_trace::hex(guid.entityId.value,4) +
                    "\\\\",\\\\"cdr_bytes\\\\":" + std::to_string(data.size()) + payload);
            }
        }
    } catch (...) {} // never substitute a diagnostic failure for write's result
    const bool result = ptr_->write(&const_cast<std::vector<uint8_t>&>(data));
    try {
        if (diagnostic_status) {
            auto& diagnostic = tfg_status::Diagnostic::instance("agent");
            if (diagnostic.requested() && diagnostic_write_id) diagnostic.emit("status_dds_write_return",
                std::string("\\\\"write_id\\\\":") + std::to_string(diagnostic_write_id) + ",\\\\"success\\\\":" + (result ? "true" : "false"));
        }
    } catch (...) {}
    return result;
}'''
    # Escape levels are deliberately checked by the pure C++ method regression.
    new = new.replace('\\\\\"', '\\\"')
    return '#include <uxr/agent/diagnostic/status_diagnostic.hpp>\n#include <uxr/agent/diagnostic/trace.hpp>\n'+replace_once(text, old, new)


def prepare_agent(source, destination):
    result = prepare(source, destination)
    dest = Path(destination)
    p = dest/'src/cpp/middleware/fastdds/FastDDSEntities.cpp'
    old = p.read_text();new = patch_agent(old);p.write_text(new)
    shutil.copyfile(PROJECT/'tools/rover_identity_probe/status_diagnostic.hpp', dest/'include/uxr/agent/diagnostic/status_diagnostic.hpp')
    trace = dest/'include/uxr/agent/diagnostic/trace.hpp'
    trace.write_text(patch_trace(trace.read_text()))
    (dest/'status.patch').write_text(''.join(difflib.unified_diff(old.splitlines(True),new.splitlines(True),'a/'+str(p.relative_to(dest)),'b/'+str(p.relative_to(dest)))))
    result['status_original_sha256'] = hashlib.sha256(old.encode()).hexdigest()
    result['status_patched_sha256'] = hashlib.sha256(new.encode()).hexdigest()
    result['base_trace_header_sha256'] = result['trace_header_sha256']
    result['trace_header_sha256'] = hashlib.sha256(trace.read_bytes()).hexdigest()
    result['status_header_sha256'] = hashlib.sha256((trace.parent/'status_diagnostic.hpp').read_bytes()).hexdigest()
    (dest/'tfg-status-input.json').write_text(json.dumps(result,indent=2)+'\n')
    return result


def patch_trace(text):
    """Only this opt-in build: existing envelope, same stderr, no blocking sink."""
    text = '#include <fcntl.h>\n#include <sys/stat.h>\n'+text
    text = replace_once(text,'namespace tfg_xrce_trace {','''namespace tfg_xrce_trace {
inline std::atomic<unsigned>& status_trace_losses() {
    static std::atomic<unsigned> value{0};return value;
}''')
    text = replace_once(text, '    const ssize_t result = ::write(STDERR_FILENO, data, size);',
        '''    int target = STDERR_FILENO;
    if (std::getenv("TFG_STATUS_DIAGNOSTIC")) {
        static const int sink = []() {
            int fd = ::open("/proc/self/fd/2",O_WRONLY|O_NONBLOCK|O_CLOEXEC);
            struct stat original{},copy{};
            if(fd<0)return -1;
            if(::fstat(2,&original)||::fstat(fd,&copy)||!S_ISFIFO(original.st_mode)||
               original.st_ino!=copy.st_ino||original.st_dev!=copy.st_dev) {
                ::close(fd);return -1;
            }
            return fd;
        }();
        target = sink;
    }
    const ssize_t result = ::write(target, data, size);''')
    text = replace_once(text, '        std::lock_guard<std::mutex> lock(mutex);',
        '''        std::unique_lock<std::mutex> lock(mutex,std::defer_lock);
        if (std::getenv("TFG_STATUS_DIAGNOSTIC")) {
            if(!lock.try_lock()){++status_trace_losses();return;}
        } else lock.lock();''')
    text = replace_once(text,'        if (failed || count>=512) return;',
        '        if (failed || count>=512) {++status_trace_losses();return;}')
    text = replace_once(text,'            ",\\\"sequence\\\":" + std::to_string(count) + "," + selected + "}\\n";',
        '            ",\\\"sequence\\\":" + std::to_string(count) + ",\\\"diagnostic_lost\\\":" + std::to_string(status_trace_losses().load()) + "," + selected + "}\\n";')
    return replace_once(text,'diagnostic_write(line.data(),line.size()) != static_cast<ssize_t>(line.size())) failed=true;',
        'diagnostic_write(line.data(),line.size()) != static_cast<ssize_t>(line.size())) {failed=true;++status_trace_losses();}')
