"""Prepare an isolated ArduPilot Gazebo source-point diagnostic. Never installs/runs."""
import argparse
import difflib
import hashlib
import json
from pathlib import Path
import shutil

PINNED={'src/ArduPilotPlugin.cc':'e00c3fc98e2ef8e37c9fb6a537c4f6fb599b1e8e3f90885d4916eaa04baac868',
        'include/SocketUDP.hh':'3f135a3dae3fa8834f3da67cea677a8f5a13707fa216d32c166144ac088db650'}


def prepare(source,destination):
    source,destination=Path(source).resolve(),Path(destination).resolve()
    if destination.exists() or destination.is_relative_to(source) or source.is_relative_to(destination):
        raise ValueError('Fresh, disjoint diagnostic source copy required')
    for name,sha in PINNED.items():
        if hashlib.sha256((source/name).read_bytes()).hexdigest()!=sha:raise ValueError('Source changed: '+name)
    shutil.copytree(source,destination);changes=[]
    def write(name,old,text):
        (destination/name).write_text(text)
        changes.extend(difflib.unified_diff(old.splitlines(True),text.splitlines(True),'a/'+name,'b/'+name))
    name='include/SocketUDP.hh';old=(source/name).read_text()
    if old.count('private:')!=1:raise ValueError('Socket getter insertion ambiguous')
    write(name,old,old.replace('private:','    // Diagnostic source copy only: observe the existing socket; no new IO.\n    int diagnostic_fd() const { return fd; }\n\nprivate:'))
    name='src/ArduPilotPlugin.cc';old=(source/name).read_text();text='#include "model_trace.hpp"\n'+old
    needle='  gzlog << "[" << this->dataPtr->modelName << "] "\n        << "ArduPilot ready to fly.'
    if text.count(needle)!=1:raise ValueError('Configure hook ambiguous')
    text=text.replace(needle,'''  tfg_model_trace::configured(this,this->dataPtr->model.Entity(),this->dataPtr->sock.diagnostic_fd(),
      this->dataPtr->modelXYZToAirplaneXForwardZDown,this->dataPtr->gazeboXYZToNED);
'''+needle)
    needle='    // require the duration since sim start in seconds'
    if text.count(needle)!=1:raise ValueError('Pose hook ambiguous')
    text=text.replace(needle,'''    tfg_model_trace::state(this,_simTime,_ecm,this->dataPtr->model.Entity(),this->dataPtr->imuLink,
        wldGToBdyG,velWldG,wldAToBdyA,velWldA);
'''+needle)
    needle='#if DEBUG_JSON_IO\n    auto bytes_sent =\n#endif\n    this->dataPtr->sock.sendto('
    if text.count(needle)!=1:raise ValueError('Send hook ambiguous')
    text=text.replace(needle,'    const auto bytes_sent = this->dataPtr->sock.sendto(')
    needle='        this->dataPtr->fcu_port_out);\n\n#if DEBUG_JSON_IO'
    if text.count(needle)!=1:raise ValueError('Send completion hook ambiguous')
    text=text.replace(needle,'''        this->dataPtr->fcu_port_out);
    tfg_model_trace::sent(this,this->dataPtr->sock.diagnostic_fd(),this->dataPtr->fcu_address,
        this->dataPtr->fcu_port_out,bytes_sent,this->dataPtr->json_str.size());

#if DEBUG_JSON_IO''')
    write(name,old,text)
    here=Path(__file__).with_name('model_probe')
    shutil.copyfile(here/'model_trace.hpp',destination/'include/model_trace.hpp')
    shutil.copyfile(Path(__file__).with_name('trace.hpp'),destination/'include/trace.hpp')
    # Build only the copied plugin. Existing dependencies; no install targets.
    cmake='''cmake_minimum_required(VERSION 3.16)
project(tfg_model_source_diagnostic LANGUAGES CXX)
find_package(gz-sim8 REQUIRED)
find_package(OpenSSL REQUIRED)
find_package(PkgConfig REQUIRED)
pkg_check_modules(TFG_TINYXML2 REQUIRED IMPORTED_TARGET tinyxml2)
add_library(TFGArduPilotIdentity SHARED src/ArduPilotPlugin.cc src/SocketUDP.cc src/Util.cc)
target_compile_features(TFGArduPilotIdentity PRIVATE cxx_std_17)
target_include_directories(TFGArduPilotIdentity PRIVATE include)
target_link_libraries(TFGArduPilotIdentity PRIVATE gz-sim8::gz-sim8 OpenSSL::Crypto PkgConfig::TFG_TINYXML2)
'''
    (destination/'CMakeLists.txt').write_text(cmake)
    (destination/'model-source.patch').write_text(''.join(changes))
    result={'schema':'tfg.model-source-preparation/1','originals':PINNED,'source':str(source),'copy':str(destination),
            'prepared':{str(p.relative_to(destination)):hashlib.sha256(p.read_bytes()).hexdigest() for p in [destination/'src/ArduPilotPlugin.cc',destination/'include/SocketUDP.hh',destination/'include/model_trace.hpp',destination/'CMakeLists.txt']},
            'default_enabled':False,'movement_authorized':False,'loaded':False}
    (destination/'inputs.json').write_text(json.dumps(result,indent=2)+'\n');return result


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('source');p.add_argument('destination');a=p.parse_args()
    print(json.dumps(prepare(a.source,a.destination),indent=2))
